"""Project and backlog endpoints, the manager's "assign ready tasks", and notifications."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.principal import CurrentPrincipal, MutatingPrincipal
from app.db.session import get_db
from app.models import Project
from app.schemas.projects import (
    BacklogIn,
    EvaluationOut,
    NotificationOut,
    NotificationPage,
    PlanItemOut,
    ProgressOut,
    ProjectCreate,
    ProjectOut,
    ValidationOut,
)
from app.services import notifications as notes
from app.services import projects as svc
from app.services.errors import NotFoundError
from app.services.idempotency import run_idempotent
from app.services.orchestrator.backlog import ValidationReport

router = APIRouter(tags=["projects"])
DB = Annotated[Session, Depends(get_db)]
RequiredKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)]


def _out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        team_id=p.team_id,
        name=p.name,
        description=p.description,
        status=p.status,
        created_at=p.created_at,
        backlog_approved_at=p.backlog_approved_at,
        started_at=p.started_at,
    )


def _report(r: ValidationReport, count: int) -> ValidationOut:
    return ValidationOut(
        ok=r.ok,
        errors=r.errors,
        warnings=r.warnings,
        task_count=count,
        can_start_immediately=r.roots,
    )


def _items(body: BacklogIn) -> list[svc.BacklogTaskIn]:
    return [
        svc.BacklogTaskIn(
            key=t.key,
            title=t.title,
            priority=t.priority,
            description=t.description,
            acceptance_criteria=t.acceptance_criteria,
            due_at=t.due_at,
            estimated_effort_hours=t.estimated_effort_hours,
            required_skills=tuple(t.required_skills),
            depends_on=tuple(t.depends_on),
            requires_approval=t.requires_approval,
            evidence_policy=t.evidence_policy,
        )
        for t in body.tasks
    ]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, p: MutatingPrincipal, db: DB) -> ProjectOut:
    project = svc.create_project(
        db, p, team_id=body.team_id, name=body.name, description=body.description
    )
    db.commit()
    db.refresh(project)
    return _out(project)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(p: CurrentPrincipal, db: DB) -> list[ProjectOut]:
    return [_out(x) for x in svc.list_projects(db, p)]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> ProjectOut:
    return _out(svc.load_project(db, p, project_id, manage=False))


@router.post("/projects/{project_id}/backlog/validate", response_model=ValidationOut)
def validate_backlog(
    project_id: uuid.UUID, body: BacklogIn, p: MutatingPrincipal, db: DB
) -> ValidationOut:
    """Dry run: report every problem. Saves nothing."""
    project = svc.load_project(db, p, project_id, manage=True)
    return _report(svc.validate(db, project, _items(body)), len(body.tasks))


@router.post("/projects/{project_id}/backlog/import", response_model=ValidationOut)
def import_backlog(
    project_id: uuid.UUID,
    body: BacklogIn,
    p: MutatingPrincipal,
    db: DB,
    response: Response,
    key: RequiredKey,
):
    def action():
        report = svc.import_backlog(db, p, project_id, _items(body))
        code = status.HTTP_201_CREATED if report.ok else status.HTTP_422_UNPROCESSABLE_ENTITY
        return code, _report(report, len(body.tasks)).model_dump(mode="json")

    code, out, replayed = run_idempotent(
        db,
        actor_user_id=p.user_id,
        key=key,
        endpoint=f"POST /projects/{project_id}/backlog/import",
        payload=body.model_dump(mode="json"),
        action=action,
    )
    response.status_code = code
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return out


@router.post("/projects/{project_id}/approve-backlog", response_model=ValidationOut)
def approve_backlog(project_id: uuid.UUID, p: MutatingPrincipal, db: DB) -> ValidationOut:
    report = svc.approve_backlog(db, p, project_id)
    db.commit()
    return _report(report, len(report.order))


@router.post("/projects/{project_id}/start", response_model=EvaluationOut)
def start_project(project_id: uuid.UUID, p: MutatingPrincipal, db: DB) -> EvaluationOut:
    result = svc.start_project(db, p, project_id)
    db.commit()
    return EvaluationOut(**result.as_dict())


@router.get("/projects/{project_id}/progress", response_model=ProgressOut)
def project_progress(project_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> ProgressOut:
    return ProgressOut(**svc.progress(db, p, project_id))


@router.get("/projects/{project_id}/assignment-plan", response_model=list[PlanItemOut])
def assignment_plan(project_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> list[PlanItemOut]:
    """What VoiceFlow would assign right now, with reasons. Changes nothing (read back for
    confirmation before "assign the ready tasks")."""
    return [PlanItemOut(**i) for i in svc.assignment_plan(db, p, project_id)]


@router.post("/projects/{project_id}/assign-ready", response_model=EvaluationOut)
def assign_ready(
    project_id: uuid.UUID, p: MutatingPrincipal, db: DB, response: Response, key: RequiredKey
):
    """Manager command: assign every ready task by priority, skills and workload."""

    def action():
        result = svc.assign_ready(db, p, project_id)
        return status.HTTP_200_OK, EvaluationOut(**result.as_dict()).model_dump(mode="json")

    code, out, replayed = run_idempotent(
        db,
        actor_user_id=p.user_id,
        key=key,
        endpoint=f"POST /projects/{project_id}/assign-ready",
        payload={},
        action=action,
    )
    response.status_code = code
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return out


# ----------------------------------------------------------------------------- notifications


@router.get("/notifications", response_model=NotificationPage, tags=["notifications"])
def list_notifications(
    p: CurrentPrincipal,
    db: DB,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationPage:
    rows, total, unread = notes.list_for(
        db, p.user_id, unread_only=unread_only, limit=limit, offset=offset
    )
    return NotificationPage(
        items=[
            NotificationOut(
                id=n.id,
                kind=n.kind,
                title=n.title,
                body=n.body,
                task_id=n.task_id,
                project_id=n.project_id,
                created_at=n.created_at,
                read=n.read_at is not None,
            )
            for n in rows
        ],
        total=total,
        unread=unread,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/notifications/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["notifications"],
)
def read_notification(notification_id: uuid.UUID, p: MutatingPrincipal, db: DB) -> None:
    if not notes.mark_read(db, p.user_id, notification_id):
        raise NotFoundError("Notification not found.")
    db.commit()
