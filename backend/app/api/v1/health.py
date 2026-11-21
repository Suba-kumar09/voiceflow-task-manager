"""Public health/readiness endpoints (the only unauthenticated routes, per CLAUDE.md)."""

import importlib.util
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.core.config import get_settings
from app.db.migrations import head_revision
from app.db.session import DatabaseNotConfiguredError, current_migration_revision, get_engine
from app.voice.onnx_whisper import missing_files

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


class HealthOut(BaseModel):
    status: Literal["ok"]


SpeechState = Literal["ok", "model_missing", "not_installed", "disabled"]


class ReadinessOut(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable", "not_configured"]
    migrations: Literal["up_to_date", "pending", "unknown"]
    # Information only: without speech, people can still type their commands.
    speech: SpeechState = "disabled"


def speech_state() -> SpeechState:
    """Is speech recognition set up? Cheap: checks files and packages, loads no model."""
    s = get_settings()
    if s.stt_provider == "disabled":
        return "disabled"
    if s.stt_provider == "faster-whisper":
        return "ok" if importlib.util.find_spec("faster_whisper") else "not_installed"
    if not importlib.util.find_spec("onnxruntime"):
        return "not_installed"
    if not s.stt_model_dir or missing_files(Path(s.stt_model_dir)):
        return "model_missing"
    return "ok"


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Liveness: the process is up. Does not touch the database."""
    return HealthOut(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessOut,
    responses={503: {"model": ReadinessOut}},
)
def ready(response: Response) -> ReadinessOut:
    """Readiness: database reachable and migrated to the latest revision (+ speech status)."""
    speech = speech_state()
    try:
        current = current_migration_revision(get_engine())
    except DatabaseNotConfiguredError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessOut(
            status="not_ready", database="not_configured", migrations="unknown", speech=speech
        )
    except Exception:
        logger.warning("Readiness check: database unavailable", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessOut(
            status="not_ready", database="unavailable", migrations="unknown", speech=speech
        )

    if current != head_revision():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessOut(status="not_ready", database="ok", migrations="pending", speech=speech)
    return ReadinessOut(status="ready", database="ok", migrations="up_to_date", speech=speech)
