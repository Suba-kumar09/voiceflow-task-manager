"""Team reports (managers) and notification preferences (everyone)."""

from datetime import datetime, time
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.auth.principal import CurrentPrincipal, MutatingPrincipal
from app.db.session import get_db
from app.models import Organization, User
from app.models.common import utcnow
from app.services import reports as svc
from app.services.reminders import in_quiet_hours

router = APIRouter(tags=["reports"])
DB = Annotated[Session, Depends(get_db)]


class TaskLineOut(BaseModel):
    id: str
    key: str | None
    title: str
    assignee: str | None
    due_at: datetime | None
    status: str


class PersonLoadOut(BaseModel):
    id: str
    name: str
    active: int
    limit: int
    state: str


class TeamSummaryOut(BaseModel):
    period: str
    period_label: str
    timezone: str
    start: datetime
    completed: int
    in_progress: int
    blocked: int
    awaiting_review: int
    open_unassigned: int
    overdue: list[TaskLineOut]
    due_soon: list[TaskLineOut]
    people: list[PersonLoadOut]
    spoken: str


@router.get("/reports/team-summary", response_model=TeamSummaryOut)
def team_summary(
    p: CurrentPrincipal, db: DB, period: Literal["today", "week"] = "today"
) -> TeamSummaryOut:
    s = svc.summary(db, p, period)
    return TeamSummaryOut(
        period=s.period,
        period_label=s.period_label,
        timezone=s.timezone,
        start=s.start,
        completed=s.completed,
        in_progress=s.in_progress,
        blocked=s.blocked,
        awaiting_review=s.awaiting_review,
        open_unassigned=s.open_unassigned,
        overdue=[TaskLineOut(**vars(t)) for t in s.overdue],
        due_soon=[TaskLineOut(**vars(t)) for t in s.due_soon],
        people=[
            PersonLoadOut(id=x.id, name=x.name, active=x.active, limit=x.limit, state=x.state)
            for x in s.people
        ],
        spoken=svc.summary_speech(s),
    )


class PreferencesIn(BaseModel):
    voice_announcements: bool | None = None
    quiet_start: time | None = Field(default=None, description="HH:MM, organisation time zone")
    quiet_end: time | None = None
    clear_quiet_hours: bool = False

    @model_validator(mode="after")
    def _both_or_neither(self):
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("Give both quiet_start and quiet_end, or neither.")
        return self


class PreferencesOut(BaseModel):
    voice_announcements: bool
    quiet_start: time | None
    quiet_end: time | None
    timezone: str
    quiet_now: bool


def _prefs(db: Session, user: User) -> PreferencesOut:
    org = db.get(Organization, user.organization_id)
    tz = org.timezone if org else "UTC"
    return PreferencesOut(
        voice_announcements=user.voice_announcements,
        quiet_start=user.quiet_start,
        quiet_end=user.quiet_end,
        timezone=tz,
        quiet_now=in_quiet_hours(user, utcnow().astimezone(ZoneInfo(tz))),
    )


@router.get("/users/me/preferences", response_model=PreferencesOut, tags=["people"])
def get_preferences(p: CurrentPrincipal, db: DB) -> PreferencesOut:
    return _prefs(db, db.get(User, p.user_id))


@router.patch("/users/me/preferences", response_model=PreferencesOut, tags=["people"])
def update_preferences(body: PreferencesIn, p: MutatingPrincipal, db: DB) -> PreferencesOut:
    user = db.get(User, p.user_id)
    if body.voice_announcements is not None:
        user.voice_announcements = body.voice_announcements
    if body.clear_quiet_hours:
        user.quiet_start = user.quiet_end = None
    elif body.quiet_start is not None:
        user.quiet_start, user.quiet_end = body.quiet_start, body.quiet_end
    db.commit()
    return _prefs(db, user)
