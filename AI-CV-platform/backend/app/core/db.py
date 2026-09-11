"""SQLAlchemy engine/session setup."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.sqlalchemy_url,
    connect_args={"check_same_thread": False} if settings.sqlalchemy_url.startswith("sqlite") else {},
    future=True,
)

if settings.sqlalchemy_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session for background workers (batch test, runtime)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401  - register mappers

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    _dedupe_runtime_sessions()
    _ensure_runtime_session_unique()


def _add_missing_columns() -> None:
    """Bring an existing database up to date with the models.

    The MVP has no migration tool; adding columns to a table that already holds
    data is the only schema change that happens in practice, and SQLite can do
    that in place as long as the new column is nullable or has a constant
    default. Anything more involved needs a real migration.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        missing = [column for column in table.columns if column.name not in present]
        if not missing:
            continue
        with engine.begin() as connection:
            for column in missing:
                default = getattr(column.default, "arg", None) if column.default is not None else None
                clause = ""
                if isinstance(default, bool):
                    clause = f" DEFAULT {int(default)}"
                elif isinstance(default, (int, float)):
                    clause = f" DEFAULT {default}"
                elif isinstance(default, str):
                    escaped = default.replace("'", "''")
                    clause = f" DEFAULT '{escaped}'"
                if not column.nullable:
                    if not clause:
                        continue  # no safe value for existing rows
                    clause += " NOT NULL"
                type_sql = column.type.compile(engine.dialect)
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {type_sql}{clause}'
                )
            for index in table.indexes:
                index.create(bind=connection, checkfirst=True)


def _dedupe_runtime_sessions() -> None:
    from app.services.runtime_service import collapse_duplicate_sessions

    db = SessionLocal()
    try:
        collapse_duplicate_sessions(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_runtime_session_unique() -> None:
    inspector = inspect(engine)
    if "runtime_sessions" not in inspector.get_table_names():
        return
    for index in inspector.get_indexes("runtime_sessions"):
        if index.get("unique") and index.get("column_names") == ["project_id"]:
            return
    for constraint in inspector.get_unique_constraints("runtime_sessions"):
        if constraint.get("column_names") == ["project_id"]:
            return
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_runtime_sessions_project_id "
            "ON runtime_sessions (project_id)"
        )
