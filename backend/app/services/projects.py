"""Projects: create, import + validate backlog, approve, start, progress, plans.

Lifecycle: DRAFT (backlog editable) -> READY (backlog approved) -> ACTIVE (orchestrator runs).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.auth.principal import Principal
from app.models import (
    ACTIVE_HOLD_STATUSES,
    AuditOutcome,
    EvidencePolicy,
    Organization,
    Project,
    ProjectStatus,
    Skill,
    Task,
    TaskDependency,
    TaskPriority,
    TaskRequiredSkill,
    TaskStatus,
    TaskStatusHistory,
    Team,
    TeamMembership,
    User,
    UserSkill,
)
from app.models.common import utcnow
from app.services.audit import record_audit
from app.services.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RuleViolationError,
)
from app.services.orchestrator import service as orchestrator
from app.services.orchestrator.backlog import BacklogItem, ValidationReport, validate_backlog
from app.services.orchestrator.planner import Outcome

# ----------------------------------------------------------------------------- access


def _is_manager_of(p: Principal, team_id: uuid.UUID) -> bool:
    return p.is_admin or team_id in p.managed_team_ids


def _deny(db: Session, p: Principal, project_id, action: str, message: str) -> None:
    record_audit(
        db,
        action=f"project.{action}",
        outcome=AuditOutcome.DENIED,
        organization_id=p.organization_id,
        actor_user_id=p.user_id,
        target_type="project",
        target_id=project_id,
    )
    db.commit()
    raise PermissionDeniedError(message)


def load_project(
    db: Session, p: Principal, project_id: uuid.UUID, *, manage: bool, lock: bool = False
) -> Project:
    stmt = select(Project).where(Project.id == project_id)
    if lock:
        stmt = stmt.with_for_update()
    project = db.execute(stmt).scalar_one_or_none()
    if project is None or project.organization_id != p.organization_id:
        raise NotFoundError("Project not found.")
    if manage and not _is_manager_of(p, project.team_id):
        _deny(db, p, project.id, "manage", "Only a manager of this team can do that.")
    if not manage and not (
        _is_manager_of(p, project.team_id) or project.team_id in p.member_team_ids
    ):
        _deny(db, p, project.id, "view", "You do not have access to this project.")
    return project


# ----------------------------------------------------------------------------- create / list


def create_project(
    db: Session, p: Principal, *, team_id: uuid.UUID, name: str, description: str
) -> Project:
    team = db.get(Team, team_id)
    if team is None or team.organization_id != p.organization_id:
        raise NotFoundError("Team not found.")
    if not _is_manager_of(p, team.id):
        _deny(db, p, team.id, "create", "You can only create projects for teams you manage.")
    project = Project(
        organization_id=p.organization_id,
        team_id=team.id,
        name=name.strip(),
        description=description.strip(),
        status=ProjectStatus.DRAFT,
        created_by=p.user_id,
    )
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A project with this name already exists.") from exc
    record_audit(
        db,
        action="project.create",
        outcome=AuditOutcome.SUCCESS,
        organization_id=p.organization_id,
        actor_user_id=p.user_id,
        target_type="project",
        target_id=project.id,
    )
    db.flush()
    return project


def list_projects(db: Session, p: Principal) -> list[Project]:
    stmt = select(Project).where(Project.organization_id == p.organization_id)
    if not p.is_admin:
        visible = p.managed_team_ids | p.member_team_ids
        stmt = stmt.where(Project.team_id.in_(visible)) if visible else stmt.where(False)
    return list(db.execute(stmt.order_by(Project.created_at, Project.id)).scalars())


# ----------------------------------------------------------------------------- backlog


@dataclass(frozen=True)
class BacklogTaskIn:
    key: str
    title: str
    priority: str | None
    description: str = ""
    acceptance_criteria: str = ""
    due_at: datetime | None = None
    estimated_effort_hours: Decimal | None = None
    required_skills: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    requires_approval: bool = False
    evidence_policy: EvidencePolicy = EvidencePolicy.NONE


def _skill_maps(db: Session, project: Project) -> tuple[dict[str, uuid.UUID], set[str]]:
    catalog = {
        name.lower(): sid
        for sid, name in db.execute(
            select(Skill.id, Skill.name).where(Skill.organization_id == project.organization_id)
        ).all()
    }
    team_skills = set(
        db.execute(
            select(func.lower(Skill.name))
            .join(UserSkill, UserSkill.skill_id == Skill.id)
            .join(TeamMembership, TeamMembership.user_id == UserSkill.user_id)
            .where(TeamMembership.team_id == project.team_id)
        ).scalars()
    )
    return catalog, team_skills


def validate(db: Session, project: Project, items: list[BacklogTaskIn]) -> ValidationReport:
    catalog, team_skills = _skill_maps(db, project)
    return validate_backlog(
        [
            BacklogItem(
                i.key.strip(),
                i.title,
                i.priority,
                tuple(d.strip() for d in i.depends_on),
                i.required_skills,
            )
            for i in items
        ],
        set(catalog),
        team_skills,
    )


def import_backlog(
    db: Session, p: Principal, project_id: uuid.UUID, items: list[BacklogTaskIn]
) -> ValidationReport:
    project = load_project(db, p, project_id, manage=True, lock=True)
    if project.status is not ProjectStatus.DRAFT:
        raise ConflictError("The backlog can only be imported while the project is a draft.")
    if db.execute(select(Task.id).where(Task.project_id == project.id).limit(1)).first():
        raise ConflictError("This project already has a backlog.")
    report = validate(db, project, items)
    if not report.ok:
        return report

    catalog, _ = _skill_maps(db, project)
    org = db.get(Organization, project.organization_id)
    by_key: dict[str, Task] = {}
    for it in items:
        task = Task(
            organization_id=project.organization_id,
            team_id=project.team_id,
            project_id=project.id,
            external_key=it.key.strip(),
            title=it.title.strip(),
            description=it.description.strip(),
            acceptance_criteria=it.acceptance_criteria.strip(),
            priority=TaskPriority(it.priority.upper()),
            status=TaskStatus.DRAFT,
            created_by=p.user_id,
            due_at=it.due_at,
            timezone=org.timezone if org else "UTC",
            estimated_effort_hours=it.estimated_effort_hours,
            requires_approval=it.requires_approval,
            evidence_policy=it.evidence_policy,
        )
        db.add(task)
        by_key[task.external_key] = task
    db.flush()
    for it in items:
        task = by_key[it.key.strip()]
        db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=None,
                to_status=TaskStatus.DRAFT,
                action="import",
                actor_user_id=p.user_id,
                details={},
            )
        )
        for skill in {s.strip().lower() for s in it.required_skills}:
            db.add(TaskRequiredSkill(task_id=task.id, skill_id=catalog[skill]))
        for dep in {d.strip() for d in it.depends_on}:
            db.add(TaskDependency(task_id=task.id, depends_on_task_id=by_key[dep].id))
    record_audit(
        db,
        action="project.backlog_import",
        outcome=AuditOutcome.SUCCESS,
        organization_id=project.organization_id,
        actor_user_id=p.user_id,
        target_type="project",
        target_id=project.id,
        details={"tasks": len(items), "warnings": len(report.warnings)},
    )
    db.flush()
    return report


def _db_graph_report(db: Session, project: Project) -> ValidationReport:
    """Re-validate the stored backlog (defence in depth before approval)."""
    rows = (
        db.execute(
            select(Task).where(Task.project_id == project.id, Task.status != TaskStatus.CANCELLED)
        )
        .scalars()
        .all()
    )
    key_of = {t.id: t.external_key or str(t.id) for t in rows}
    deps: dict[uuid.UUID, list[str]] = {}
    for tid, did in db.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(
            TaskDependency.task_id.in_(key_of)
        )
    ).all():
        deps.setdefault(tid, []).append(key_of.get(did, str(did)))
    catalog, team_skills = _skill_maps(db, project)
    req: dict[uuid.UUID, list[str]] = {}
    for tid, name in db.execute(
        select(TaskRequiredSkill.task_id, Skill.name)
        .join(Skill, Skill.id == TaskRequiredSkill.skill_id)
        .where(TaskRequiredSkill.task_id.in_(key_of))
    ).all():
        req.setdefault(tid, []).append(name)
    items = [
        BacklogItem(
            key_of[t.id],
            t.title,
            t.priority.value,
            tuple(deps.get(t.id, [])),
            tuple(req.get(t.id, [])),
        )
        for t in rows
    ]
    return validate_backlog(items, set(catalog), team_skills)


def approve_backlog(db: Session, p: Principal, project_id: uuid.UUID) -> ValidationReport:
    project = load_project(db, p, project_id, manage=True, lock=True)
    if project.status is not ProjectStatus.DRAFT:
        raise ConflictError(
            f"Only a draft project's backlog can be approved (this one is {project.status.value})."
        )
    report = _db_graph_report(db, project)
    if not report.ok:
        raise RuleViolationError(
            "The backlog has problems: " + " ".join(report.errors), code="backlog_invalid"
        )
    drafts = (
        db.execute(
            select(Task)
            .where(Task.project_id == project.id, Task.status == TaskStatus.DRAFT)
            .with_for_update()
        )
        .scalars()
        .all()
    )
    for task in drafts:
        task.status = TaskStatus.UNASSIGNED
        db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=TaskStatus.DRAFT,
                to_status=TaskStatus.UNASSIGNED,
                action="approve_backlog",
                actor_user_id=p.user_id,
                details={},
            )
        )
    project.status = ProjectStatus.READY
    project.backlog_approved_at = utcnow()
    project.backlog_approved_by = p.user_id
    record_audit(
        db,
        action="project.approve_backlog",
        outcome=AuditOutcome.SUCCESS,
        organization_id=project.organization_id,
        actor_user_id=p.user_id,
        target_type="project",
        target_id=project.id,
        details={"tasks": len(drafts)},
    )
    db.flush()
    return report


def start_project(
    db: Session, p: Principal, project_id: uuid.UUID
) -> orchestrator.EvaluationResult:
    project = load_project(db, p, project_id, manage=True, lock=True)
    if project.status is not ProjectStatus.READY:
        raise ConflictError(
            "Only a project with an approved backlog can be started "
            f"(this one is {project.status.value})."
        )
    project.status = ProjectStatus.ACTIVE
    project.started_at = utcnow()
    record_audit(
        db,
        action="project.start",
        outcome=AuditOutcome.SUCCESS,
        organization_id=project.organization_id,
        actor_user_id=p.user_id,
        target_type="project",
        target_id=project.id,
    )
    db.flush()
    return orchestrator.evaluate(db, project.id, requested_by=p)


def assign_ready(db: Session, p: Principal, project_id: uuid.UUID) -> orchestrator.EvaluationResult:
    """The manager's "assign the ready tasks by priority" command."""
    project = load_project(db, p, project_id, manage=True)
    if project.status is not ProjectStatus.ACTIVE:
        raise ConflictError("Start the project before assigning its tasks.")
    return orchestrator.evaluate(db, project.id, requested_by=p)


def assignment_plan(db: Session, p: Principal, project_id: uuid.UUID) -> list[dict]:
    """Dry run: what the orchestrator WOULD do now. Changes nothing."""
    project = load_project(db, p, project_id, manage=True)
    if project.status not in (ProjectStatus.READY, ProjectStatus.ACTIVE):
        raise ConflictError("Approve the backlog first.")
    return orchestrator.plan_view(orchestrator.build_plan(db, project))


# ----------------------------------------------------------------------------- progress


def progress(db: Session, p: Principal, project_id: uuid.UUID) -> dict:
    """Project-grounded breakdown (CLAUDE.md 4.9).

    Separates ready vs waiting vs blocked vs awaiting review vs needs a manager decision.
    """
    project = load_project(db, p, project_id, manage=False)
    counts = dict(
        db.execute(
            select(Task.status, func.count())
            .where(Task.project_id == project.id)
            .group_by(Task.status)
        ).all()
    )
    ready_ids = set(db.execute(orchestrator.ready_task_ids_query(project.id)).scalars())
    unassigned = counts.get(TaskStatus.UNASSIGNED, 0)
    needs_decision: list[dict] = []
    if project.status is ProjectStatus.ACTIVE or project.status is ProjectStatus.READY:
        for item in orchestrator.build_plan(db, project).items:
            if item.outcome is Outcome.NO_QUALIFIED:
                needs_decision.append(
                    {
                        "task_id": str(item.task.id),
                        "key": item.task.key,
                        "title": item.task.title,
                        "reason": item.reason,
                    }
                )
    total = sum(counts.values())
    completed = counts.get(TaskStatus.COMPLETED, 0)
    return {
        "project_id": str(project.id),
        "name": project.name,
        "status": project.status.value,
        "total": total,
        "completed": completed,
        "percent_complete": round(completed * 100 / total) if total else 0,
        "in_progress": sum(
            counts.get(s, 0)
            for s in (TaskStatus.ASSIGNED, TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS)
        ),
        "ready_to_assign": len(ready_ids) - len(needs_decision),
        "waiting_on_dependencies": unassigned - len(ready_ids),
        "blocked_by_issue": counts.get(TaskStatus.BLOCKED, 0),
        "awaiting_review": counts.get(TaskStatus.PENDING_REVIEW, 0),
        "needs_decision": needs_decision,
        "draft": counts.get(TaskStatus.DRAFT, 0),
        "cancelled": counts.get(TaskStatus.CANCELLED, 0),
    }


def project_team(db: Session, p: Principal, project_id: uuid.UUID) -> list[dict]:
    """Managers' view of the project's people: skills, workload and what each is doing.
    Restricted to managers/admins (employees only see their own work — decision A7)."""
    project = load_project(db, p, project_id, manage=True)
    people = db.execute(
        select(User, TeamMembership.membership_role)
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .where(TeamMembership.team_id == project.team_id, User.organization_id == p.organization_id)
        .order_by(TeamMembership.membership_role.desc(), User.display_name)
    ).all()
    ids = [u.id for u, _ in people]
    skills: dict[uuid.UUID, list[str]] = {}
    for uid, name in db.execute(
        select(UserSkill.user_id, Skill.name)
        .join(Skill, Skill.id == UserSkill.skill_id)
        .where(UserSkill.user_id.in_(ids))
        .order_by(Skill.name)
    ).all():
        skills.setdefault(uid, []).append(name)
    held: dict[uuid.UUID, list[Task]] = {}
    for task in db.execute(
        select(Task)
        .where(Task.assigned_to.in_(ids), Task.status.in_(ACTIVE_HOLD_STATUSES))
        .order_by(Task.updated_at.desc())
    ).scalars():
        held.setdefault(task.assigned_to, []).append(task)
    done = dict(
        db.execute(
            select(Task.assigned_to, func.count())
            .where(Task.project_id == project.id, Task.status == TaskStatus.COMPLETED)
            .group_by(Task.assigned_to)
        ).all()
    )
    out = []
    for user, role in people:
        tasks_held = held.get(user.id, [])
        current = tasks_held[0] if tasks_held else None
        out.append(
            {
                "id": str(user.id),
                "display_name": user.display_name,
                "membership_role": role.value,
                "is_active": user.is_active,
                "skills": skills.get(user.id, []),
                "active_tasks": len(tasks_held),
                "wip_limit": user.wip_limit,
                "completed_in_project": done.get(user.id, 0),
                "current_task": (
                    {
                        "id": str(current.id),
                        "key": current.external_key,
                        "title": current.title,
                        "status": current.status.value,
                    }
                    if current
                    else None
                ),
            }
        )
    return out


def project_dependencies(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, list[str]]:
    pred = aliased(Task)
    out: dict[uuid.UUID, list[str]] = {}
    for tid, key in db.execute(
        select(TaskDependency.task_id, pred.external_key)
        .join(pred, pred.id == TaskDependency.depends_on_task_id)
        .join(Task, Task.id == TaskDependency.task_id)
        .where(Task.project_id == project_id)
        .order_by(pred.external_key)
    ).all():
        out.setdefault(tid, []).append(key)
    return out


def set_user_skills(
    db: Session, p: Principal, user_id: uuid.UUID, skill_names: list[str]
) -> list[str]:
    """Admin/manager helper used by seeds and tests; creates catalog entries if missing."""
    names = sorted({s.strip() for s in skill_names if s.strip()}, key=str.lower)
    existing = {
        n.lower(): sid
        for sid, n in db.execute(
            select(Skill.id, Skill.name).where(Skill.organization_id == p.organization_id)
        ).all()
    }
    for n in names:
        if n.lower() not in existing:
            s = Skill(organization_id=p.organization_id, name=n)
            db.add(s)
            db.flush()
            existing[n.lower()] = s.id
    for n in names:
        if not db.execute(
            select(UserSkill.id).where(
                UserSkill.user_id == user_id, UserSkill.skill_id == existing[n.lower()]
            )
        ).first():
            db.add(UserSkill(user_id=user_id, skill_id=existing[n.lower()]))
    db.flush()
    return names
