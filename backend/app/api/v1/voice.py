"""Voice turns: audio (or typed text) -> transcript -> intent -> action + spoken reply.

Phase 6: navigation and read-only questions only. Nothing here changes tasks.
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agent.intents import Intent
from app.agent.voice_turn import TurnResult, safe_handle_text
from app.auth.principal import MutatingPrincipal, Principal
from app.core.config import get_settings
from app.db.session import get_db
from app.models import TeamMembership, User
from app.services import projects as project_svc
from app.voice.audio import validate_wav
from app.voice.stt import SpeechToTextProvider, get_stt_provider

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger(__name__)
DB = Annotated[Session, Depends(get_db)]
STT = Annotated[SpeechToTextProvider, Depends(get_stt_provider)]


class TextTurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    path: str | None = Field(default=None, max_length=300, description="Screen the user is on")
    page_summary: str | None = Field(default=None, max_length=1000)


class VoiceTurnOut(BaseModel):
    transcript: str | None
    heard_clearly: bool
    intent: str
    slots: dict
    outcome: str
    speech: str
    action: dict | None
    suggestions: list[str]
    stt_ms: int | None
    total_ms: int


def _out(
    r: TurnResult, *, transcript: str | None, clear: bool, stt_ms: int | None, t0: float
) -> VoiceTurnOut:
    out = VoiceTurnOut(
        transcript=transcript,
        heard_clearly=clear,
        intent=r.intent.name,
        slots=r.intent.slots,
        outcome=r.outcome,
        speech=r.speech,
        action=r.action,
        suggestions=r.suggestions,
        stt_ms=stt_ms,
        total_ms=int((time.perf_counter() - t0) * 1000),
    )
    # No transcript in logs (privacy); intent and timings are enough to debug.
    logger.info(
        "voice turn",
        extra={
            "data": {
                "intent": out.intent,
                "outcome": out.outcome,
                "stt_ms": stt_ms,
                "total_ms": out.total_ms,
            }
        },
    )
    return out


def _hints(db: Session, p: Principal) -> list[str]:
    """Names the recogniser should expect: teammates and the user's projects."""
    team_ids = p.member_team_ids | p.managed_team_ids
    names = (
        set(
            db.execute(
                select(User.display_name)
                .join(TeamMembership, TeamMembership.user_id == User.id)
                .where(TeamMembership.team_id.in_(team_ids))
            ).scalars()
        )
        if team_ids
        else set()
    )
    names.update(x.name.replace("[DEMO] ", "") for x in project_svc.list_projects(db, p))
    return sorted(names)[:40]


@router.post("/turns", response_model=VoiceTurnOut)
def text_turn(body: TextTurnIn, p: MutatingPrincipal, db: DB) -> VoiceTurnOut:
    """Typed fallback (and test entry point): same pipeline without speech recognition."""
    t0 = time.perf_counter()
    result = safe_handle_text(db, p, body.text, path=body.path, page_summary=body.page_summary)
    return _out(result, transcript=body.text, clear=True, stt_ms=None, t0=t0)


@router.post(
    "/turns/audio",
    response_model=VoiceTurnOut,
    openapi_extra={
        "requestBody": {
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
            "required": True,
        }
    },
)
async def audio_turn(
    request: Request,
    p: MutatingPrincipal,
    db: DB,
    stt: STT,
    path: Annotated[str | None, Query(max_length=300)] = None,
    page_summary: Annotated[str | None, Query(max_length=1000)] = None,
) -> VoiceTurnOut:
    """Body: 16 kHz mono 16-bit WAV, at most 20 s. Recorded only after the user pressed talk."""
    t0 = time.perf_counter()
    clip = validate_wav(await request.body(), max_seconds=get_settings().stt_max_seconds)
    hints = await run_in_threadpool(_hints, db, p)
    transcript = await run_in_threadpool(stt.transcribe, clip.wav_bytes, hints=hints)
    if not transcript.confident:
        result = TurnResult(
            Intent("unclear"), "repeat", "Sorry, I didn't catch that clearly. Please say it again."
        )
        return _out(
            result,
            transcript=transcript.text or None,
            clear=False,
            stt_ms=transcript.latency_ms,
            t0=t0,
        )
    result = await run_in_threadpool(
        lambda: safe_handle_text(db, p, transcript.text, path=path, page_summary=page_summary)
    )
    return _out(result, transcript=transcript.text, clear=True, stt_ms=transcript.latency_ms, t0=t0)
