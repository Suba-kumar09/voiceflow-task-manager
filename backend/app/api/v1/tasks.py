"""Task endpoints. Thin: validate input, call the task service, commit once."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.principal import CurrentPrincipal, MutatingPrincipal, Principal
from app.db.session import get_db
from app.models import Task, TaskStatus, User
from app.schemas.identity import Page
from app.schemas.tasks import (
    AssignIn,
    CurrentTaskOut,
    HistoryEntryOut,
    PersonRef,
    ReassignIn,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    TransitionIn,
)
from app.services.idempotency import run_idempotent
from app.services.orchestrator import service as orchestrator
from app.services.tasks import service
from app.services.tasks.lifecycle import Action

router = APIRouter(tags=["tasks"])
DB = Annotated[Session, Depends(get_db)]
RequiredKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)]
OptionalKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)]


def _to_out(db: Session, tasks: list[Task]) -> list[TaskOut]:
    ids = {t.assigned_to for t in tasks if t.assigned_to}
    names = (
        dict(db.execute(select(User.id, User.display_name).where(User.id.in_(ids))).all())
        if ids
        else {}
    )
    return [
        TaskOut(
            id=t.id,
            team_id=t.team_id,
            project_id=t.project_id,
            external_key=t.external_key,
            title=t.title,
            description=t.description,
            acceptance_criteria=t.acceptance_criteria,
            priority=t.priority,
            status=t.status,
            assignee=PersonRef(id=t.assigned_to, display_name=names[t.assigned_to])
            if t.assigned_to
            else None,
            created_by=t.created_by,
            due_at=t.due_at,
            timezone=t.timezone,
            estimated_effort_hours=t.estimated_effort_hours,
            requires_approval=t.requires_approval,
            evidence_policy=t.evidence_policy,
            version=t.version,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in tasks
    ]


def _one(db: Session, task: Task) -> TaskOut:
    db.refresh(task)  # pick up server-side timestamps
    return _to_out(db, [task])[0]


def _respond(response: Response, status_code: int, body: dict, replayed: bool) -> dict:
    response.status_code = status_code
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return body


def _mutate(
    db: Session,
    p: Principal,
    response: Response,
    *,
    key: str | None,
    endpoint: str,
    payload: dict,
    run,
    success_status: int = status.HTTP_200_OK,
) -> dict:
    def action() -> tuple[int, dict]:
        task = run()
        db.flush()
        return success_status, _one(db, task).model_dump(mode="json")

    if key is None:
        code, body = action()
        db.commit()
        return _respond(response, code, body, False)
    code, body, replayed = run_idempotent(
        db, actor_user_id=p.user_id, key=key, endpoint=endpoint, payload=payload, action=action
    )
    return _respond(response, code, body, replayed)


# ----------------------------------------------------------------------------- create / read


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskCreate, p: MutatingPrincipal, db: DB, response: Response, key: RequiredKey
):
    new = service.NewTask(**body.model_dump())
    return _mutate(
        db,
        p,
        response,
        key=key,
        endpoint="POST /tasks",
        payload=body.model_dump(mode="json"),
        run=lambda: service.create_task(db, p, new),
        success_status=status.HTTP_201_CREATED,
    )


@router.get("/tasks", response_model=Page[TaskOut])
def list_tasks(
    p: CurrentPrincipal,
    db: DB,
    status_filter: Annotated[list[TaskStatus] | None, Query(alias="status")] = None,
    team_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[TaskOut]:
    tasks, total = service.list_tasks(
        db, p, statuses=status_filter or (), team_id=team_id, limit=limit, offset=offset
    )
    return Page(items=_to_out(db, tasks), total=total, limit=limit, offset=offset)


@router.get("/me/tasks", response_model=Page[TaskOut])
def my_tasks(
    p: CurrentPrincipal,
    db: DB,
    status_filter: Annotated[list[TaskStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[TaskOut]:
    tasks, total = service.list_tasks(
        db, p, statuses=status_filter or (), assigned_to_me=True, limit=limit, offset=offset
    )
    return Page(items=_to_out(db, tasks), total=total, limit=limit, offset=offset)


@router.get("/me/tasks/current", response_model=CurrentTaskOut)
def my_current_task(p: CurrentPrincipal, db: DB) -> CurrentTaskOut:
    task = service.current_task(db, p)
    return CurrentTaskOut(task=_to_out(db, [task])[0] if task else None)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> TaskOut:
    return _to_out(db, [service.get_task(db, p, task_id)])[0]


@router.get("/tasks/{task_id}/history", response_model=list[HistoryEntryOut])
def task_history(task_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> list[HistoryEntryOut]:
    return [
        HistoryEntryOut(
            action=h.action,
            from_status=h.from_status,
            to_status=h.to_status,
            actor_user_id=h.actor_user_id,
            reason=h.reason,
            details=h.details,
            occurred_at=h.occurred_at,
        )
        for h in service.history(db, p, task_id)
    ]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: uuid.UUID, body: TaskUpdate, p: MutatingPrincipal, db: DB) -> TaskOut:
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    task = service.update_task(db, p, task_id, body.version, changes)
    db.commit()
    return _one(db, task)


# ----------------------------------------------------------------------------- assignment


@router.post("/tasks/{task_id}/assign", response_model=TaskOut)
def assign(
    task_id: uuid.UUID,
    body: AssignIn,
    p: MutatingPrincipal,
    db: DB,
    response: Response,
    key: RequiredKey,
):
    return _mutate(
        db,
        p,
        response,
        key=key,
        endpoint=f"POST /tasks/{task_id}/assign",
        payload=body.model_dump(mode="json"),
        run=lambda: service.assign_task(
            db, p, task_id, body.assignee_id, override_capacity=body.override_capacity
        ),
    )


@router.post("/tasks/{task_id}/reassign", response_model=TaskOut)
def reassign(
    task_id: uuid.UUID,
    body: ReassignIn,
    p: MutatingPrincipal,
    db: DB,
    response: Response,
    key: RequiredKey,
):
    return _mutate(
        db,
        p,
        response,
        key=key,
        endpoint=f"POST /tasks/{task_id}/reassign",
        payload=body.model_dump(mode="json"),
        run=lambda: service.reassign_task(
            db,
            p,
            task_id,
            body.assignee_id,
            body.reason,
            override_capacity=body.override_capacity,
        ),
    )


# ----------------------------------------------------------------------------- lifecycle actions


def _add_transition_route(path: str, action: Action, summary: str) -> None:
    def endpoint(
        task_id: uuid.UUID,
        p: MutatingPrincipal,
        db: DB,
        response: Response,
        key: OptionalKey = None,
        body: TransitionIn | None = None,
    ):
        body = body or TransitionIn()
        out = _mutate(
            db,
            p,
            response,
            key=key,
            endpoint=f"POST /tasks/{task_id}/{path}",
            payload=body.model_dump(mode="json"),
            run=lambda: service.transition(
                db, p, task_id, action, reason=body.reason, note=body.note, link=body.link
            ),
        )
        if action in _REEVALUATE_AFTER:
            # The user's change is committed; now let the orchestrator assign newly ready work.
            orchestrator.reevaluate_after_task_change(db, task_id)
        return out

    endpoint.__name__ = f"task_{action.value}"
    router.add_api_route(
        f"/tasks/{{task_id}}/{path}",
        endpoint,
        methods=["POST"],
        response_model=TaskOut,
        summary=summary,
    )


_REEVALUATE_AFTER = {
    Action.REQUEST_COMPLETION,  # may complete the task (no review needed)
    Action.APPROVE_COMPLETION,  # unlocks dependent tasks and frees the person
    Action.DECLINE,  # task back in the pool; someone else may take it
    Action.UNASSIGN,
    Action.CANCEL,  # frees the person
}

for _path, _action, _summary in [
    ("publish", Action.PUBLISH, "Move a draft into the task pool"),
    ("unassign", Action.UNASSIGN, "Manager returns the task to the pool (reason required)"),
    ("accept", Action.ACCEPT, "Assignee accepts the task"),
    ("decline", Action.DECLINE, "Assignee declines; task returns to the pool (reason required)"),
    ("start", Action.START, "Assignee starts work"),
    ("block", Action.BLOCK, "Assignee reports a blocker (reason required)"),
    ("resume", Action.RESUME, "Blocker resolved; work continues"),
    ("request-completion", Action.REQUEST_COMPLETION, "Assignee reports the task done"),
    ("approve-completion", Action.APPROVE_COMPLETION, "Manager approves completion"),
    ("reject-completion", Action.REJECT_COMPLETION, "Manager rejects completion (reason required)"),
    ("cancel", Action.CANCEL, "Manager cancels the task (reason required)"),
]:
    _add_transition_route(_path, _action, _summary)
