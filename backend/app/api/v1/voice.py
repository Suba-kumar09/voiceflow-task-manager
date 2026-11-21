"""Voice turns: audio (or typed text) -> transcript -> harness -> spoken reply.

Navigation and questions are answered directly. Changes go through the execution harness:
resolved from permitted data, checked, read back, and executed only after "yes".
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agent.harness import TurnRecord, run_turn
from app.agent.intents import Intent
from app.agent.voice_turn import TurnResult
from app.auth.principal import CurrentPrincipal, MutatingPrincipal, Principal
from app.core.config import get_settings
from app.core.security import read_body_limited
from app.db.session import get_db
from app.models import AgentTrace, TeamMembership, User
from app.services import projects as project_svc
from app.services.errors import PermissionDeniedError
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
    outcome: str  # ok | confirm | clarify | done | denied | failed | repeat | unsupported | not_yet
    speech: str
    action: dict | None
    suggestions: list[str]
    checks: list[dict]
    plan: list[dict]
    awaiting_confirmation: bool
    trace_id: str | None
    stt_ms: int | None
    total_ms: int


def _out(
    r: TurnResult,
    *,
    transcript: str | None,
    clear: bool,
    stt_ms: int | None,
    t0: float,
    trace_id=None,
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
        checks=r.checks,
        plan=r.plan,
        awaiting_confirmation=r.awaiting_confirmation,
        trace_id=str(trace_id) if trace_id else None,
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


def _from_record(rec: TurnRecord, **kw) -> VoiceTurnOut:
    return _out(rec.result, trace_id=rec.trace_id, **kw)


def _rate_limit(request: Request, p: Principal) -> None:
    if not request.app.state.voice_limiter.hit(f"user:{p.user_id}"):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many voice commands in a minute. Please wait a moment and try again.",
        )


@router.post("/turns", response_model=VoiceTurnOut)
def text_turn(body: TextTurnIn, request: Request, p: MutatingPrincipal, db: DB) -> VoiceTurnOut:
    """Typed fallback (and test entry point): same harness without speech recognition."""
    _rate_limit(request, p)
    t0 = time.perf_counter()
    rec = run_turn(db, p, body.text, path=body.path, page_summary=body.page_summary, channel="text")
    return _from_record(rec, transcript=body.text, clear=True, stt_ms=None, t0=t0)


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
    _rate_limit(request, p)
    t0 = time.perf_counter()
    max_seconds = get_settings().stt_max_seconds
    # 16 kHz x 16-bit mono = 32 000 bytes per second, plus room for the WAV header.
    body = await read_body_limited(request, int(max_seconds * 32_000) + 4096)
    clip = validate_wav(body, max_seconds=max_seconds)
    hints = await run_in_threadpool(_hints, db, p)
    transcript = await run_in_threadpool(stt.transcribe, clip.wav_bytes, hints=hints)
    if not transcript.confident:
        # Never act on unclear speech — not even a "yes".
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
    rec = await run_in_threadpool(
        lambda: run_turn(
            db,
            p,
            transcript.text,
            path=path,
            page_summary=page_summary,
            channel="voice",
            stt_ms=transcript.latency_ms,
        )
    )
    return _from_record(
        rec, transcript=transcript.text, clear=True, stt_ms=transcript.latency_ms, t0=t0
    )


@router.get("/traces", tags=["voice"])
def list_traces(
    p: CurrentPrincipal, db: DB, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[dict]:
    """Administrators only: how recent voice turns were understood and handled."""
    if not p.is_admin:
        raise PermissionDeniedError("Only administrators can view agent traces.")
    rows = db.execute(
        select(AgentTrace, User.display_name)
        .join(User, User.id == AgentTrace.user_id)
        .where(AgentTrace.organization_id == p.organization_id)
        .order_by(AgentTrace.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": str(t.id),
            "at": t.created_at.isoformat(),
            "user": name,
            "channel": t.channel,
            "transcript": t.transcript,
            "intent": t.intent,
            "slots": t.slots,
            "tool": t.tool,
            "outcome": t.outcome,
            "steps": t.steps,
            "speech": t.speech,
            "error": t.error,
            "stt_ms": t.stt_ms,
            "total_ms": t.total_ms,
        }
        for t, name in rows
    ]
