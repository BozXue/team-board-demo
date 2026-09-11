"""Runtime configuration.

Local deployment first: everything lives under ``DATA_DIR`` and a single
SQLite file, so a project can be zipped and moved between machines.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_prefix="AICV_", extra="ignore"
    )

    app_name: str = "戴纳 AI 引导式视觉平台"
    version: str = "0.3.0-mvp"

    data_dir: Path = BASE_DIR / "data"
    database_url: str = ""

    # Uploaded images larger than this are downscaled for preview/pipeline work;
    # the original file is always kept on disk.
    max_preview_side: int = 2048
    thumbnail_side: int = 256

    # Batch test / runtime worker pool
    max_workers: int = 4

    # AI Copilot LLM backend. Without a key the Copilot falls back to the
    # built-in rule based planner, so the platform stays usable offline.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 60.0

    cors_origins: list[str] = ["*"]

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'platform.db'}"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.projects_dir, self.cache_dir, self.models_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
