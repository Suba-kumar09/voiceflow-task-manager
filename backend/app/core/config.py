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
    # onnx-whisper: Whisper base.en on ONNX Runtime (Microsoft-signed, loads under Windows
    # Smart App Control). faster-whisper: same model on CTranslate2 (blocked on the dev laptop).
    stt_provider: Literal["onnx-whisper", "faster-whisper", "disabled"] = "onnx-whisper"
    # onnx-whisper model folder (python -m app.cli.fetch_stt_model downloads it there).
    stt_model_dir: str | None = None
    stt_model: str = "base.en"  # faster-whisper only: downloaded to HF_HOME
    stt_cpu_threads: int = 4
    stt_max_seconds: float = 20.0
    # Per-person limit on voice commands (speech recognition is the expensive part).
    voice_turns_per_minute: int = 30

    # --- Retention (Phase 10; app/services/retention.py, run by the maintenance worker) ---
    retention_trace_days: int = Field(default=30, ge=1)  # voice traces hold what people said
    retention_notification_days: int = Field(default=90, ge=1)  # read notifications only

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"

    @property
    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
