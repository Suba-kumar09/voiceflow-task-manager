"""Extension requests and progress updates (on-screen and voice share these services)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.principal import CurrentPrincipal, MutatingPrincipal
from app.db.session import get_db
from app.models import User
from app.services import requests as svc

router = APIRouter(tags=["requests"])
DB = Annotated[Session, Depends(get_db)]


class ExtensionIn(BaseModel):
    requested_due_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=1000)


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class ExtensionOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    task_title: str
    task_key: str | None
    project_id: uuid.UUID | None
    requested_by: str
    previous_due_at: datetime | None
    requested_due_at: datetime
    reason: str
    status: str
    decision_note: str | None
    created_at: datetime


class ProgressIn(BaseModel):
    percent: int | None = Field(default=None, ge=0, le=100)
    note: str | None = Field(default=None, max_length=1000)


class ProgressOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    percent: int | None
    note: str | None
    created_at: datetime


def _ext(db: Session, req, task) -> ExtensionOut:
    who = db.get(User, req.requested_by)
    return ExtensionOut(
        id=req.id,
        task_id=task.id,
        task_title=task.title,
        task_key=task.external_key,
        project_id=task.project_id,
        requested_by=who.display_name if who else "",
        previous_due_at=req.previous_due_at,
        requested_due_at=req.requested_due_at,
        reason=req.reason,
        status=req.status.value,
        decision_note=req.decision_note,
        created_at=req.created_at,
    )


@router.post(
    "/tasks/{task_id}/extension-requests",
    response_model=ExtensionOut,
    status_code=status.HTTP_201_CREATED,
)
def request_extension(
    task_id: uuid.UUID, body: ExtensionIn, p: MutatingPrincipal, db: DB
) -> ExtensionOut:
    req = svc.request_extension(db, p, task_id, body.requested_due_at, body.reason)
    db.commit()
    db.refresh(req)
    return _ext(db, req, db.get(svc.Task, req.task_id))


@router.get("/extension-requests", response_model=list[ExtensionOut])
def list_extension_requests(
    p: CurrentPrincipal, db: DB, pending_only: bool = True, project_id: uuid.UUID | None = None
) -> list[ExtensionOut]:
    return [
        _ext(db, r, t)
        for r, t in svc.list_extensions(db, p, pending_only=pending_only, project_id=project_id)
    ]


def _decide(
    request_id: uuid.UUID, body: DecisionIn | None, p, db: Session, approve: bool
) -> ExtensionOut:
    req = svc.decide_extension(
        db, p, request_id, approve=approve, note=(body.note if body else None)
    )
    db.commit()
    db.refresh(req)
    return _ext(db, req, db.get(svc.Task, req.task_id))


@router.post("/extension-requests/{request_id}/approve", response_model=ExtensionOut)
def approve_extension(
    request_id: uuid.UUID, p: MutatingPrincipal, db: DB, body: DecisionIn | None = None
) -> ExtensionOut:
    return _decide(request_id, body, p, db, approve=True)


@router.post("/extension-requests/{request_id}/deny", response_model=ExtensionOut)
def deny_extension(
    request_id: uuid.UUID, p: MutatingPrincipal, db: DB, body: DecisionIn | None = None
) -> ExtensionOut:
    return _decide(request_id, body, p, db, approve=False)


@router.post(
    "/tasks/{task_id}/progress", response_model=ProgressOut, status_code=status.HTTP_201_CREATED
)
def report_progress(
    task_id: uuid.UUID, body: ProgressIn, p: MutatingPrincipal, db: DB
) -> ProgressOut:
    row = svc.report_progress(db, p, task_id, percent=body.percent, note=body.note)
    db.commit()
    db.refresh(row)
    return ProgressOut(
        id=row.id,
        task_id=row.task_id,
        percent=row.percent,
        note=row.note,
        created_at=row.created_at,
    )
