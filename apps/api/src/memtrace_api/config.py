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

    app_name: str = Field(default="MemTrace API", validation_alias="APP_NAME")
    app_env: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    app_version: str = Field(default=APP_VERSION, validation_alias="APP_VERSION")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )

    mock_mode: bool = Field(default=True, validation_alias="MOCK_MODE")
    llm_api_key: SecretStr | None = Field(default=None, validation_alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.deepseek.com", validation_alias="LLM_BASE_URL")
    llm_model: str = Field(default="deepseek-v4-flash", validation_alias="LLM_MODEL")
    memtrace_data_dir: Path = Field(default=DEFAULT_DATA_DIR, validation_alias="MEMTRACE_DATA_DIR")

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def blank_secret_is_missing(cls, value: object) -> object:
        """Treat an empty .env placeholder as an absent credential."""

        if isinstance(value, str) and not value.strip():
            return None
        return value

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

    @property
    def provider_mode(self) -> Literal["mock", "real"]:
        return "mock" if self.mock_mode else "real"

    @property
    def has_llm_api_key(self) -> bool:
        return self.llm_api_key is not None and bool(self.llm_api_key.get_secret_value())


def get_settings() -> Settings:
    """Build settings once at application construction time."""

    return Settings()
