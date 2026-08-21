"""Application configuration loaded from the repository-root environment file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    """Validated process configuration.

    The absolute ``env_file`` path is deliberate: launching Uvicorn from the
    repository root or from ``apps/api`` must load the same local settings.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = Field(
        default="MemTrace API",
        min_length=1,
        max_length=128,
        validation_alias="APP_NAME",
    )
    app_env: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    app_version: str = Field(
        default=APP_VERSION,
        min_length=1,
        max_length=32,
        validation_alias="APP_VERSION",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )

    mock_mode: bool = Field(default=True, validation_alias="MOCK_MODE")
    llm_api_key: SecretStr | None = Field(default=None, validation_alias="LLM_API_KEY")
    llm_base_url: str = Field(
        default="https://api.deepseek.com",
        min_length=1,
        max_length=2_048,
        validation_alias="LLM_BASE_URL",
    )
    llm_model: str = Field(
        default="deepseek-v4-flash",
        min_length=1,
        max_length=128,
        validation_alias="LLM_MODEL",
    )
    memtrace_data_dir: Path = Field(default=DEFAULT_DATA_DIR, validation_alias="MEMTRACE_DATA_DIR")
    memtrace_web_dist: Path | None = Field(default=None, validation_alias="MEMTRACE_WEB_DIST")
    provider_timeout_seconds: float = Field(
        default=60.0, gt=0, le=300, validation_alias="PROVIDER_TIMEOUT_SECONDS"
    )
    max_tasks: int = Field(default=100, ge=1, le=10_000, validation_alias="MAX_TASKS")
    max_subscribers_per_task: int = Field(
        default=8, ge=1, le=100, validation_alias="MAX_SUBSCRIBERS_PER_TASK"
    )
    subscriber_queue_size: int = Field(
        default=64, ge=4, le=1_024, validation_alias="SUBSCRIBER_QUEUE_SIZE"
    )
    heartbeat_seconds: float = Field(
        default=15.0, gt=0, le=60, validation_alias="SSE_HEARTBEAT_SECONDS"
    )
    mock_chunk_delay_ms: int = Field(
        default=250, ge=0, le=5_000, validation_alias="MOCK_CHUNK_DELAY_MS"
    )

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def blank_secret_is_missing(cls, value: object) -> object:
        """Treat an empty .env placeholder as an absent credential."""

        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("app_name", "app_version", "llm_base_url", "llm_model", mode="before")
    @classmethod
    def strip_bounded_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("memtrace_data_dir", mode="before")
    @classmethod
    def resolve_data_dir(cls, value: object) -> Path:
        """Resolve relative runtime paths against the repository, not the CWD."""

        if value is None or (isinstance(value, str) and not value.strip()):
            return DEFAULT_DATA_DIR
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @field_validator("memtrace_web_dist", mode="before")
    @classmethod
    def resolve_web_dist(cls, value: object) -> Path | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @property
    def provider_mode(self) -> Literal["mock", "real"]:
        return "mock" if self.mock_mode else "real"

    @property
    def has_llm_api_key(self) -> bool:
        return self.llm_api_key is not None and bool(self.llm_api_key.get_secret_value())


def get_settings() -> Settings:
    """Build settings once at application construction time."""

    return Settings()
