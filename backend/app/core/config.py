"""Application settings, loaded from environment variables / backend/.env.

All variables use the VOICEFLOW_ prefix (see .env.example at the repo root).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOICEFLOW_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "VoiceFlow"
    environment: Literal["development", "test", "production"] = "development"
    default_timezone: str = "Asia/Kolkata"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # No default with credentials: the app must be configured explicitly.
    database_url: str | None = None
    test_database_url: str | None = None

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
