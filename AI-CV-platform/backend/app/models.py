"""Persistence model: Project / Dataset / Annotation / Pipeline / Run.

The three core structures of the platform are Project, Pipeline(Version) and
the dataset (ImageAsset + Annotation); everything else hangs off them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """Timestamps that stay UTC-aware across a database that can't store zones.

    SQLite hands back naive datetimes, which then serialize without an offset
    and are read as local time by the browser. Storing normalised UTC and
    re-attaching the zone on load keeps every timestamp unambiguous end to end.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:  # noqa: ANN001
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    task_type: Mapped[str] = mapped_column(String(50), default="unknown")
    # Free-form task description used by the Copilot as project memory.
    requirement: Mapped[str] = mapped_column(Text, default="")
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    user_params: Mapped[dict] = mapped_column(JSON, default=dict)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    published_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    images: Mapped[list["ImageAsset"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    label_classes: Mapped[list["LabelClass"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        order_by="LabelClass.order_index",
    )
    versions: Mapped[list["PipelineVersion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        order_by="PipelineVersion.version.desc()",
    )


class PipelineVersion(Base, TimestampMixin):
    """Project snapshot: pipeline graph + exposed user parameters."""

    __tablename__ = "pipeline_versions"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_project_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    user_params: Mapped[dict] = mapped_column(JSON, default=dict)
    published: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped[Project] = relationship(back_populates="versions")


class LabelClass(Base):
    __tablename__ = "label_classes"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_project_label"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#38bdf8")
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship(back_populates="label_classes")


class ImageAsset(Base, TimestampMixin):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    rel_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumb_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    preview_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    channels: Mapped[int] = mapped_column(Integer, default=1)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    image_format: Mapped[str] = mapped_column(String(20), default="")
    split: Mapped[str] = mapped_column(String(20), default="unassigned", index=True)
    source: Mapped[str] = mapped_column(String(30), default="upload")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    project: Mapped[Project] = relationship(back_populates="images")
    annotation: Mapped["Annotation | None"] = relationship(
        back_populates="image", cascade="all, delete-orphan", uselist=False
    )


class Annotation(Base, TimestampMixin):
    """One row per image: classification label plus geometric shapes."""

    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    image_id: Mapped[str] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), index=True, unique=True
    )
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shapes: Mapped[list] = mapped_column(JSON, default=list)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")

    image: Mapped[ImageAsset] = relationship(back_populates="annotation")


class BatchRun(Base, TimestampMixin):
    __tablename__ = "batch_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    split: Mapped[str] = mapped_column(String(20), default="all")
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    ok_count: Mapped[int] = mapped_column(Integer, default=0)
    ng_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str] = mapped_column(Text, default="")

    results: Mapped[list["BatchResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class BatchResult(Base):
    __tablename__ = "batch_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("batch_runs.id", ondelete="CASCADE"), index=True)
    image_id: Mapped[str] = mapped_column(String(32), index=True)
    image_name: Mapped[str] = mapped_column(String(300), default="")
    verdict: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    gt_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(10), nullable=True)
    measurements: Mapped[dict] = mapped_column(JSON, default=dict)
    artifacts: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    run: Mapped[BatchRun] = relationship(back_populates="results")


class RuntimeSession(Base, TimestampMixin):
    """A published project being executed in User Mode."""

    __tablename__ = "runtime_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True
    )
    version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="stopped")
    source: Mapped[str] = mapped_column(String(30), default="dataset")
    total: Mapped[int] = mapped_column(Integer, default=0)
    ok_count: Mapped[int] = mapped_column(Integer, default=0)
    ng_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    user_params: Mapped[dict] = mapped_column(JSON, default=dict)
    alarm: Mapped[str] = mapped_column(Text, default="")

    records: Mapped[list["RuntimeRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan",
        order_by="RuntimeRecord.created_at.desc()",
    )


class RuntimeRecord(Base):
    """One inference: what the deployed pipeline decided about one frame.

    ``project_id`` / ``device_id`` / ``model_id`` / ``confidence`` are
    denormalised out of the session and the graph so Model Monitoring can slice
    inferences across projects without replaying pipelines.
    """

    __tablename__ = "runtime_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_sessions.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    image_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    image_name: Mapped[str] = mapped_column(String(300), default="")
    verdict: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    source: Mapped[str] = mapped_column(String(30), default="dataset")
    device_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    model_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurements: Mapped[dict] = mapped_column(JSON, default=dict)
    artifacts: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)

    session: Mapped[RuntimeSession] = relationship(back_populates="records")


class CopilotMessage(Base):
    __tablename__ = "copilot_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="user")
    content: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class ModelAsset(Base, TimestampMixin):
    __tablename__ = "model_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    task: Mapped[str] = mapped_column(String(30), default="classification")
    framework: Mapped[str] = mapped_column(String(30), default="sklearn")
    rel_path: Mapped[str] = mapped_column(String(500), default="")
    classes: Mapped[list] = mapped_column(JSON, default=list)
    input_size: Mapped[int] = mapped_column(Integer, default=64)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class RunLog(Base):
    __tablename__ = "run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    source: Mapped[str] = mapped_column(String(40), default="platform")
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
