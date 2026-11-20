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

    # --- Sessions (server-side, HttpOnly cookie) ---
    session_cookie_name: str = "vf_session"
    session_absolute_hours: int = 12  # hard expiry after login
    session_idle_minutes: int = 120  # expires after this long without activity
    # Secure cookies need HTTPS; None = automatic (on in production only).
    session_cookie_secure: bool | None = None

    # --- Login throttling (per process; see docs/decisions.md) ---
    login_max_failures: int = 5
    login_failure_window_minutes: int = 15

    # --- Voice (Phase 6) ---
    stt_provider: Literal["faster-whisper", "disabled"] = "faster-whisper"
    stt_model: str = "base.en"  # downloaded to HF_HOME (D:\ai-cache\hf on the dev laptop)
    stt_cpu_threads: int = 4
    stt_max_seconds: float = 20.0

    @property
    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
