"""Execution harness: the ONLY path from a spoken command to a change in data.

  understand (rules) -> resolve from permitted data -> check -> read back -> "yes" -> execute once

- Nothing is executed without an explicit "yes" to a pending action that belongs to the same
  user, has not expired (2 minutes) and has not been used (row-locked, single use).
- Execution calls the same services as the on-screen buttons, which re-check identity,
  permissions, lifecycle rules, workload and dependencies. Stored arguments are never trusted
  on their own.
- Every turn is traced (agent_traces); the services write the audit events.
"""

import difflib
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agent.dates import local_now, parse_spoken_date, spoken
from app.agent.intents import Intent, parse
from app.agent.voice_turn import (
    TurnResult,
    _current_project_id,
    _display,
    resolve_project,
    safe_handle_text,
)
from app.auth.principal import Principal
from app.models import (
    AgentPendingAction,
    AgentTrace,
    EvidencePolicy,
    MembershipRole,
    ProjectStatus,
    Task,
    TaskCompletionEvidence,
    TaskStatus,
    TeamMembership,
    User,
)
from app.models.common import utcnow
from app.services import projects as project_svc
from app.services import requests as requests_svc
from app.services.errors import DomainError
from app.services.notifications import team_manager_ids
from app.services.orchestrator import service as orchestrator
from app.services.orchestrator.planner import Outcome
from app.services.tasks import lifecycle
from app.services.tasks import service as task_svc
from app.services.tasks.lifecycle import Action

PENDING_TTL = timedelta(minutes=2)
CHANGE_TOOLS = {
    "task.complete",
    "task.start",
    "task.block",
    "task.resume",
    "task.approve",
    "task.reject",
    "task.assign",
    "project.assign_ready",
    "project.start",
    "task.extend",
    "task.decline",
    "task.progress",
    "extension.approve",
    "extension.deny",
}
MANAGER_TOOLS = {
    "task.approve",
    "task.reject",
    "task.assign",
    "project.assign_ready",
    "project.start",
    "extension.approve",
    "extension.deny",
}


def ok(text: str) -> dict:
    return {"text": text, "state": "ok"}


def warn(text: str) -> dict:
    return {"text": text, "state": "warn"}


def fail(text: str) -> dict:
    return {"text": text, "state": "fail"}


@dataclass
class Proposal:
    tool: str
    args: dict
    summary: str  # the read-back question ("Shall I ...?")
    checks: list[dict] = field(default_factory=list)
    awaiting: str | None = None  # "note" | "reason"
    ask: str = ""  # what to say while awaiting
    plan: list[dict] = field(default_factory=list)


class Stop(Exception):
    """A spoken refusal/clarification raised while building a proposal."""

    def __init__(self, outcome: str, speech: str, checks=None, suggestions=None) -> None:
        super().__init__(speech)
        self.result = TurnResult(
            Intent("stop"), outcome, speech, checks=checks or [], suggestions=suggestions or []
        )


# ----------------------------------------------------------------------------- resolution


def _compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _match(hint: str, items: list, label) -> list:
    """Items whose label best matches a spoken hint: exact -> contains -> fuzzy (>= 0.7)."""
    q = _compact(hint)
    exact = [i for i in items if _compact(label(i)) == q]
    if exact:
        return exact
    contains = [i for i in items if q and (q in _compact(label(i)))]
    if contains:
        return contains
    scored = [(difflib.SequenceMatcher(None, q, _compact(label(i))).ratio(), i) for i in items]
    best = max((s for s, _ in scored), default=0)
    return [i for s, i in scored if s >= 0.7 and s >= best - 0.05]


def _task_label(t: Task) -> str:
    return t.title


def _say_task(t: Task) -> str:
    return f"{t.external_key} · {t.title}" if t.external_key else t.title


def resolve_task(
    db: Session,
    p: Principal,
    hint: str,
    *,
    mine: bool,
    statuses: list[TaskStatus],
    path: str | None,
    what: str,
) -> Task:
    tasks, _ = task_svc.list_tasks(db, p, statuses=statuses, assigned_to_me=mine, limit=200)
    if not mine and not p.is_admin:
        tasks = [t for t in tasks if t.team_id in p.managed_team_ids]
    here = _current_project_id(path)
    if not hint:
        local = [t for t in tasks if here and t.project_id == here] or tasks
        if len(local) == 1:
            return local[0]
        if not local:
            tip = ""
            if mine and (p.is_admin or p.managed_team_ids):
                tip = " To accept finished work from your team, say: approve it."
            raise Stop("clarify", f"You have no {what} right now.{tip}")
        names = ", ".join(t.title for t in local[:4])
        raise Stop("clarify", f"Which one? {names}.", suggestions=[t.title for t in local[:3]])
    found = _match(hint, tasks, _task_label) or _match(hint, tasks, lambda t: t.external_key or "")
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        names = ", ".join(t.title for t in found[:4])
        raise Stop(
            "clarify",
            f"I found more than one: {names}. Which one?",
            suggestions=[t.title for t in found[:3]],
        )
    names = ", ".join(t.title for t in tasks[:4])
    raise Stop(
        "clarify",
        f"I couldn't find {hint} among your {what}." + (f" You have: {names}." if names else ""),
    )


def resolve_person(db: Session, task: Task, spoken: str) -> User:
    people = (
        db.execute(
            select(User)
            .join(TeamMembership, TeamMembership.user_id == User.id)
            .where(
                TeamMembership.team_id == task.team_id,
                TeamMembership.membership_role == MembershipRole.MEMBER,
                User.is_active.is_(True),
            )
            .order_by(User.display_name)
        )
        .scalars()
        .all()
    )
    q = _compact(spoken)
    exact = [
        u for u in people if q in (_compact(u.display_name), _compact(u.display_name.split()[0]))
    ]
    found = (
        exact
        or _match(spoken, people, lambda u: u.display_name.split()[0])
        or _match(spoken, people, lambda u: u.display_name)
    )
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise Stop("clarify", "Which person? " + ", ".join(u.display_name for u in found) + ".")
    raise Stop(
        "clarify",
        f"I couldn't find {spoken} in this task's team. The team has: "
        + ", ".join(u.display_name for u in people)
        + ".",
    )


def _manager_names(db: Session, task: Task) -> str:
    names = [db.get(User, uid).display_name for uid in team_manager_ids(db, task.team_id)]
    return " and ".join(names) if names else "your manager"


# ----------------------------------------------------------------------------- proposals


def _propose(db: Session, p: Principal, intent: Intent, path: str | None) -> Proposal:
    s = intent.slots
    manager = p.is_admin or bool(p.managed_team_ids)
    if intent.name in MANAGER_TOOLS and not manager:
        raise Stop("denied", "Only a manager can do that.")

    if intent.name == "task.complete":
        task = resolve_task(
            db,
            p,
            s.get("task", ""),
            mine=True,
            path=path,
            what="active tasks",
            statuses=[
                TaskStatus.IN_PROGRESS,
                TaskStatus.ASSIGNED,
                TaskStatus.ACCEPTED,
                TaskStatus.BLOCKED,
            ],
        )
        checks = [ok(f"Matched to {_say_task(task)}"), ok("You are the assignee")]
        if task.status is not TaskStatus.IN_PROGRESS:
            word = "blocked" if task.status is TaskStatus.BLOCKED else "not started yet"
            hint = (
                "Say “I'm unblocked” first."
                if task.status is TaskStatus.BLOCKED
                else f"Say “I've started {task.title}” first."
            )
            raise Stop(
                "clarify", f"{task.title} is {word}. {hint}", checks + [fail(f"The task is {word}")]
            )
        checks.append(ok("The task is in progress"))
        if task.acceptance_criteria:
            checks.append(ok(f"Done when: {task.acceptance_criteria}"))
        if task.evidence_policy is EvidencePolicy.LINK:
            raise Stop(
                "clarify",
                f"{task.title} needs a link as evidence. Please use Report done on screen to add it.",
                checks + [fail("Needs a link — please add it on screen")],
            )
        review = lifecycle.needs_review(task.requires_approval, task.evidence_policy)
        note = s.get("note")
        args = {"task_id": str(task.id), "note": note}
        if task.evidence_policy is EvidencePolicy.NOTE and not note:
            checks.append(warn("This task needs a short completion note"))
            return Proposal(
                "task.complete",
                args,
                "",
                checks,
                awaiting="note",
                ask=f"Before I send {task.title} for review, it needs a short completion note. What should the note say?",
            )
        return Proposal("task.complete", args, _complete_question(db, task, note, review), checks)

    if intent.name == "task.start":
        task = resolve_task(
            db,
            p,
            s.get("task", ""),
            mine=True,
            path=path,
            what="new tasks",
            statuses=[TaskStatus.ASSIGNED, TaskStatus.ACCEPTED],
        )
        return Proposal(
            "task.start",
            {"task_id": str(task.id)},
            f"Mark {task.title} as started?",
            [ok(f"Matched to {_say_task(task)}"), ok("It is assigned to you and not started")],
        )

    if intent.name == "task.block":
        task = resolve_task(
            db,
            p,
            s.get("task", ""),
            mine=True,
            path=path,
            what="active tasks",
            statuses=[TaskStatus.IN_PROGRESS, TaskStatus.ASSIGNED, TaskStatus.ACCEPTED],
        )
        checks = [ok(f"Matched to {_say_task(task)}")]
        args = {"task_id": str(task.id), "reason": s.get("reason")}
        if not args["reason"]:
            return Proposal(
                "task.block",
                args,
                "",
                checks,
                awaiting="reason",
                ask=f"What is blocking {task.title}?",
            )
        return Proposal("task.block", args, _block_question(db, task, args["reason"]), checks)

    if intent.name == "task.resume":
        task = resolve_task(
            db,
            p,
            s.get("task", ""),
            mine=True,
            path=path,
            what="blocked tasks",
            statuses=[TaskStatus.BLOCKED],
        )
        return Proposal(
            "task.resume",
            {"task_id": str(task.id)},
            f"Mark {task.title} as unblocked and back in progress?",
            [ok(f"Matched to {_say_task(task)}")],
        )

    if intent.name in ("task.approve", "task.reject"):
        task = resolve_task(
            db,
            p,
            s.get("task", ""),
            mine=False,
            path=path,
            what="tasks awaiting review",
            statuses=[TaskStatus.PENDING_REVIEW],
        )
        who = task.assigned_to and db.get(User, task.assigned_to).display_name
        checks = [ok(f"{_say_task(task)} is awaiting your review"), ok(f"Reported done by {who}")]
        evidence = (
            db.execute(
                select(TaskCompletionEvidence)
                .where(TaskCompletionEvidence.task_id == task.id)
                .order_by(TaskCompletionEvidence.submitted_at.desc())
            )
            .scalars()
            .first()
        )
        if evidence:
            checks.append(ok(f"Their {evidence.kind.value.lower()}: “{evidence.content}”"))
        if intent.name == "task.approve":
            return Proposal(
                "task.approve",
                {"task_id": str(task.id)},
                f"Approve {task.title} from {who}?",
                checks,
            )
        args = {"task_id": str(task.id), "reason": s.get("reason")}
        if not args["reason"]:
            return Proposal(
                "task.reject",
                args,
                "",
                checks,
                awaiting="reason",
                ask=f"What still needs to be done on {task.title}?",
            )
        return Proposal(
            "task.reject",
            args,
            f"Send {task.title} back to {who} because: {args['reason']}?",
            checks,
        )

    if intent.name == "task.assign":
        task = resolve_task(
            db,
            p,
            s.get("task", ""),
            mine=False,
            path=path,
            what="open tasks",
            statuses=[TaskStatus.UNASSIGNED],
        )
        person = resolve_person(db, task, s["person"])
        checks = [
            ok(f"Matched to {_say_task(task)}"),
            ok(f"{person.display_name} is in this task's team"),
        ]
        waiting = task_svc.unmet_dependencies(db, task.id)
        if waiting:
            raise Stop(
                "clarify",
                f"{task.title} can't be assigned yet. It is waiting on {', '.join(waiting)}.",
                checks + [fail("Waiting on unfinished tasks")],
            )
        checks.append(ok("All its dependencies are done"))
        return Proposal(
            "task.assign",
            {"task_id": str(task.id), "assignee_id": str(person.id)},
            f"Assign {task.title} to {person.display_name}?",
            checks,
        )

    if intent.name in ("project.assign_ready", "project.start"):
        project = _resolve_project_for(
            db,
            p,
            s.get("project"),
            path,
            ProjectStatus.ACTIVE if intent.name == "project.assign_ready" else ProjectStatus.READY,
        )
        plan = orchestrator.build_plan(db, project)
        rows = [
            {
                "key": i.task.key,
                "title": i.task.title,
                "priority": i.task.priority,
                "outcome": i.outcome.value,
                "assignee": i.assignee.name if i.assignee else None,
                "reason": i.reason,
            }
            for i in plan.items
        ]
        assign = [i for i in plan.items if i.outcome is Outcome.ASSIGN]
        checks = [
            ok(
                f"{len(plan.items)} task{'s are' if len(plan.items) != 1 else ' is'} ready (dependencies done)"
            ),
            ok("Ranked by priority, then due date"),
            ok("Checked skills, team and workload"),
        ]
        name = _display(project.name)
        if intent.name == "project.start":
            return Proposal(
                "project.start",
                {"project_id": str(project.id)},
                f"Start {name}? I will assign {len(assign)} task{'s' if len(assign) != 1 else ''} straight away.",
                checks,
                plan=rows,
            )
        if not assign:
            others = "; ".join(f"{i.task.title}: {i.reason}" for i in plan.items[:3])
            raise Stop(
                "ok",
                "Nothing can be assigned right now."
                + (f" {others}" if others else " No tasks are ready."),
                checks,
            )
        read_out = "; ".join(
            f"{i.task.title} to {i.assignee.name}"
            if i.assignee
            else f"{i.task.title} stays ready, because {i.reason[0].lower()}{i.reason[1:]}"
            for i in plan.items[:5]
        )
        return Proposal(
            "project.assign_ready",
            {"project_id": str(project.id)},
            f"By priority: {read_out}. Shall I assign {len(assign)} task{'s' if len(assign) != 1 else ''}?",
            checks,
            plan=rows,
        )

    if intent.name == "task.extend":
        task = resolve_task(
            db,
            p,
            s.get("task", ""),
            mine=True,
            path=path,
            what="active tasks",
            statuses=list(requests_svc.ACTIVE),
        )
        checks = [ok(f"Matched to {_say_task(task)}"), ok("You are the assignee")]
        checks.append(
            ok(f"Current due date: {spoken(task.due_at, task.timezone)}")
            if task.due_at
            else warn("It has no due date yet")
        )
        if task.id in requests_svc.pending_by_task(db, [task.id]):
            raise Stop(
                "clarify",
                f"You already asked for more time on {task.title}. It is waiting for {_manager_names(db, task)}.",
                checks,
            )
        args = {"task_id": str(task.id), "due_at": None, "reason": s.get("reason")}
        due = parse_spoken_date(s.get("when", ""), local_now(task.timezone), _due_time(task))
        if due is not None:
            problem = _check_due(task, due)
            if problem:
                raise Stop(
                    "clarify", f"{problem} Please say a later date.", checks + [fail(problem)]
                )
            args["due_at"] = due.isoformat()
        awaiting, question = _next_step(db, "task.extend", args)
        return Proposal(
            "task.extend",
            args,
            "" if awaiting else question,
            checks,
            awaiting=awaiting,
            ask=question if awaiting else "",
        )

    if intent.name == "task.decline":
        task = resolve_task(
            db,
            p,
            s.get("task", ""),
            mine=True,
            path=path,
            what="new tasks you can decline",
            statuses=[TaskStatus.ASSIGNED],
        )
        args = {"task_id": str(task.id), "reason": s.get("reason")}
        awaiting, question = _next_step(db, "task.decline", args)
        return Proposal(
            "task.decline",
            args,
            "" if awaiting else question,
            [ok(f"Matched to {_say_task(task)}")],
            awaiting=awaiting,
            ask=question if awaiting else "",
        )

    if intent.name == "task.progress":
        task = resolve_task(
            db,
            p,
            s.get("task", ""),
            mine=True,
            path=path,
            what="active tasks",
            statuses=list(requests_svc.ACTIVE),
        )
        percent = int(s["percent"])
        if not 0 <= percent <= 100:
            raise Stop("clarify", "Progress must be between 0 and 100 percent.")
        return Proposal(
            "task.progress",
            {"task_id": str(task.id), "percent": percent},
            f"Record {task.title} as {percent} percent done?",
            [ok(f"Matched to {_say_task(task)}")],
        )

    if intent.name in ("extension.approve", "extension.deny"):
        req, task = _resolve_extension(db, p, s.get("task", ""), path)
        who = db.get(User, req.requested_by).display_name
        checks = [
            ok(f"{who} asked for more time on {_say_task(task)}"),
            ok(
                f"Until {spoken(req.requested_due_at, task.timezone)}"
                + (
                    f" (now {spoken(req.previous_due_at, task.timezone)})"
                    if req.previous_due_at
                    else ""
                )
            ),
            ok(f"Their reason: “{req.reason}”"),
        ]
        if intent.name == "extension.approve":
            return Proposal(
                "extension.approve",
                {"request_id": str(req.id)},
                f"Give {who} until {spoken(req.requested_due_at, task.timezone)} for {task.title}?",
                checks,
            )
        reason = s.get("reason")
        return Proposal(
            "extension.deny",
            {"request_id": str(req.id), "note": reason},
            f"Turn down {who}'s request for more time on {task.title}"
            + (f", because: {reason}?" if reason else "?"),
            checks,
        )

    raise Stop("unsupported", "Sorry, I can't do that yet.")


def _resolve_project_for(db, p, spoken, path, needed: ProjectStatus):
    if spoken:
        project, ambiguous = resolve_project(db, p, spoken)
        if project is None:
            options = ambiguous or project_svc.list_projects(db, p)
            raise Stop(
                "clarify",
                "Which project? " + ", ".join(_display(x.name) for x in options[:5]) + ".",
            )
    elif pid := _current_project_id(path):
        project = project_svc.load_project(db, p, pid, manage=True)
    else:
        candidates = [x for x in project_svc.list_projects(db, p) if x.status is needed]
        if len(candidates) != 1:
            raise Stop(
                "clarify",
                "Which project? "
                + (
                    ", ".join(_display(x.name) for x in candidates[:5])
                    or "You have none in that state"
                )
                + ".",
            )
        project = candidates[0]
    if project.status is not needed:
        state = {
            "DRAFT": "still a draft",
            "READY": "not started yet",
            "ACTIVE": "already active",
        }.get(project.status.value, project.status.value.lower())
        raise Stop("clarify", f"{_display(project.name)} is {state}.")
    return project


def _complete_question(db: Session, task: Task, note: str | None, review: bool) -> str:
    if review:
        q = f"Send {task.title} to {_manager_names(db, task)} for review"
        return q + (f" with your note: “{note}”?" if note else "?")
    return f"Mark {task.title} as completed? {_manager_names(db, task)} will be told."


def _block_question(db: Session, task: Task, reason: str) -> str:
    return f"Report {task.title} as blocked because: {reason}? {_manager_names(db, task)} will be told."


# ----------------------------------------------------------------------------- execution


def _execute(db: Session, p: Principal, tool: str, args: dict) -> tuple[str, uuid.UUID | None]:
    """Run the change through the normal services. Returns (spoken result, task to re-plan)."""
    tid = uuid.UUID(args["task_id"]) if "task_id" in args else None
    if tool == "task.complete":
        t = task_svc.transition(db, p, tid, Action.REQUEST_COMPLETION, note=args.get("note"))
        if t.status is TaskStatus.PENDING_REVIEW:
            return (
                f"Done. {t.title} is with {_manager_names(db, t)} for review. I've told them.",
                tid,
            )
        return f"Done. {t.title} is completed and {_manager_names(db, t)} has been told.", tid
    if tool == "task.start":
        t = task_svc.transition(db, p, tid, Action.START)
        return f"Done. {t.title} is in progress.", None
    if tool == "task.block":
        t = task_svc.transition(db, p, tid, Action.BLOCK, reason=args["reason"])
        return f"Done. {t.title} is marked blocked and {_manager_names(db, t)} has been told.", None
    if tool == "task.resume":
        t = task_svc.transition(db, p, tid, Action.RESUME)
        return f"Done. {t.title} is back in progress.", None
    if tool == "task.approve":
        t = task_svc.transition(db, p, tid, Action.APPROVE_COMPLETION)
        return f"Approved. {t.title} is completed and its owner has been told.", tid
    if tool == "task.reject":
        t = task_svc.transition(db, p, tid, Action.REJECT_COMPLETION, reason=args["reason"])
        return f"Sent back. {t.title} is in progress again and its owner has been told why.", None
    if tool == "task.assign":
        t = task_svc.assign_task(db, p, tid, uuid.UUID(args["assignee_id"]))
        return (
            f"Done. {t.title} is assigned to {db.get(User, t.assigned_to).display_name}, who has been told.",
            None,
        )
    if tool in ("project.assign_ready", "project.start"):
        pid = uuid.UUID(args["project_id"])
        result = (
            project_svc.start_project(db, p, pid)
            if tool == "project.start"
            else project_svc.assign_ready(db, p, pid)
        )
        done = result.assigned
        prefix = "Started. " if tool == "project.start" else "Done. "
        if not done:
            return prefix + "Nothing could be assigned right now.", None
        listed = ", ".join(f"{a['title']} to {a['assignee_name']}" for a in done[:5])
        return prefix + f"I assigned {listed}. Everyone has been told.", None
    if tool == "task.extend":
        t = db.get(Task, tid)
        due = datetime.fromisoformat(args["due_at"])
        requests_svc.request_extension(db, p, tid, due, args["reason"])
        current = (
            f" Your deadline stays {spoken(t.due_at, t.timezone)} until they decide."
            if t.due_at
            else ""
        )
        return (
            f"Done. I've asked {_manager_names(db, t)} for more time on {t.title}, until {spoken(due, t.timezone)}.{current}",
            None,
        )
    if tool == "task.decline":
        t = task_svc.transition(db, p, tid, Action.DECLINE, reason=args["reason"])
        return (
            f"Done. {t.title} is back in the task pool and {_manager_names(db, t)} has been told.",
            tid,
        )
    if tool == "task.progress":
        requests_svc.report_progress(db, p, tid, percent=int(args["percent"]), note=None)
        return f"Noted: {db.get(Task, tid).title} is {args['percent']} percent done.", None
    if tool in ("extension.approve", "extension.deny"):
        req = requests_svc.decide_extension(
            db,
            p,
            uuid.UUID(args["request_id"]),
            approve=tool == "extension.approve",
            note=args.get("note"),
        )
        t = db.get(Task, req.task_id)
        who = db.get(User, req.requested_by).display_name
        if tool == "extension.approve":
            return (
                f"Approved. {t.title} is now due {spoken(t.due_at, t.timezone)}, and {who} has been told.",
                None,
            )
        return f"Done. The deadline for {t.title} stays the same, and {who} has been told.", None
    raise DomainError(f"Unknown tool {tool}")


def _open_pending(db: Session, p: Principal) -> AgentPendingAction | None:
    return db.execute(
        select(AgentPendingAction)
        .where(
            AgentPendingAction.user_id == p.user_id,
            AgentPendingAction.consumed_at.is_(None),
            AgentPendingAction.expires_at > utcnow(),
        )
        .order_by(AgentPendingAction.created_at.desc())
        .with_for_update()
        .limit(1)
    ).scalar_one_or_none()


def _close(db: Session, pending: AgentPendingAction, outcome: str) -> None:
    pending.consumed_at = utcnow()
    pending.outcome = outcome


def _supersede_all(db: Session, p: Principal) -> None:
    db.execute(
        update(AgentPendingAction)
        .where(AgentPendingAction.user_id == p.user_id, AgentPendingAction.consumed_at.is_(None))
        .values(consumed_at=utcnow(), outcome="superseded")
    )


def _ask(proposal: Proposal, intent: Intent, pending_id) -> TurnResult:
    if proposal.awaiting:
        return TurnResult(
            intent, "clarify", proposal.ask, checks=proposal.checks, tool=proposal.tool
        )
    return TurnResult(
        intent,
        "confirm",
        proposal.summary,
        checks=proposal.checks,
        plan=proposal.plan,
        awaiting_confirmation=True,
        tool=proposal.tool,
        suggestions=["Yes", "Cancel"],
    )


def _strip_lead(text: str, words: str) -> str:
    return re.sub(rf"^\s*(?:{words})\b[\s:,-]*", "", text, flags=re.IGNORECASE).strip().rstrip(".")


# ----------------------------------------------------------------------------- multi-step slots

_LEADS = {
    "note": "note|my note is|the note is",
    "reason": "because|it's because|the reason is|reason",
    "date": "until|till|by|to|on",
}


def _check_due(task: Task, due: datetime) -> str | None:
    """Why a requested date is not acceptable, or None."""
    if due <= utcnow():
        return "That date has already passed."
    if task.due_at and due <= task.due_at:
        return f"That is not later than the current due date, {spoken(task.due_at, task.timezone)}."
    return None


def _next_step(db: Session, tool: str, args: dict) -> tuple[str | None, str]:
    """(field still missing, question) or (None, read-back question)."""
    task = db.get(Task, uuid.UUID(args["task_id"])) if args.get("task_id") else None
    if tool == "task.complete":
        if task.evidence_policy is EvidencePolicy.NOTE and not args.get("note"):
            return (
                "note",
                f"Before I send {task.title} for review, it needs a short completion note. What should the note say?",
            )
        return None, _complete_question(
            db,
            task,
            args.get("note"),
            lifecycle.needs_review(task.requires_approval, task.evidence_policy),
        )
    if tool == "task.block":
        if not args.get("reason"):
            return "reason", f"What is blocking {task.title}?"
        return None, _block_question(db, task, args["reason"])
    if tool == "task.reject":
        if not args.get("reason"):
            return "reason", f"What still needs to be done on {task.title}?"
        who = db.get(User, task.assigned_to).display_name if task.assigned_to else "the assignee"
        return None, f"Send {task.title} back to {who} because: {args['reason']}?"
    if tool == "task.extend":
        if not args.get("due_at"):
            return (
                "date",
                f"Until when do you need {task.title}? For example: Friday, or in three days.",
            )
        if not args.get("reason"):
            return "reason", f"Why do you need more time for {task.title}?"
        due = datetime.fromisoformat(args["due_at"])
        return None, (
            f"Ask {_manager_names(db, task)} to move {task.title} to {spoken(due, task.timezone)}, "
            f"because: {args['reason']}? The deadline changes only if they approve."
        )
    if tool == "task.decline":
        if not args.get("reason"):
            return "reason", f"Why are you declining {task.title}?"
        return (
            None,
            f"Decline {task.title} because: {args['reason']}? It goes back to the task pool and {_manager_names(db, task)} will be told.",
        )
    raise DomainError(f"No follow-up questions for {tool}")


def _fill(db: Session, pending: AgentPendingAction, text: str, intent: Intent) -> TurnResult:
    field_name = pending.awaiting
    args = dict(pending.args)
    task = db.get(Task, uuid.UUID(args["task_id"]))
    value = _strip_lead(text, _LEADS[field_name])
    if field_name == "date":
        due = parse_spoken_date(value or text, local_now(task.timezone), _due_time(task))
        problem = "I didn't catch a date." if due is None else _check_due(task, due)
        if problem:
            return TurnResult(
                intent, "clarify", f"{problem} Until when do you need it?", tool=pending.tool
            )
        args["due_at"] = due.isoformat()
        recorded = ok(f"New date: {spoken(due, task.timezone)}")
    else:
        if not value:
            return TurnResult(
                intent,
                "clarify",
                "Sorry, I didn't get that. Please say it again.",
                tool=pending.tool,
            )
        args[field_name] = value
        recorded = ok(f"{field_name.capitalize()} recorded: “{value}”")
    awaiting, question = _next_step(db, pending.tool, args)
    pending.args, pending.awaiting = args, awaiting
    pending.summary = "" if awaiting else question
    pending.expires_at = utcnow() + PENDING_TTL
    if awaiting:
        return TurnResult(intent, "clarify", question, checks=[recorded], tool=pending.tool)
    return TurnResult(
        intent,
        "confirm",
        question,
        awaiting_confirmation=True,
        tool=pending.tool,
        checks=[recorded],
        suggestions=["Yes", "Cancel"],
    )


def _due_time(task: Task) -> dtime:
    """Keep the task's usual due time of day when moving it; default 6 PM."""
    if task.due_at:
        return (
            task.due_at.astimezone(ZoneInfo(task.timezone)).time().replace(second=0, microsecond=0)
        )
    return dtime(18, 0)


def _resolve_extension(db: Session, p: Principal, hint: str, path: str | None):
    rows = [
        (r, t)
        for r, t in requests_svc.list_extensions(db, p, pending_only=True)
        if p.is_admin or t.team_id in p.managed_team_ids
    ]
    here = _current_project_id(path)
    if not hint:
        local = [x for x in rows if here and x[1].project_id == here] or rows
        if len(local) == 1:
            return local[0]
        if not local:
            raise Stop("clarify", "There are no extension requests waiting for you.")
        raise Stop("clarify", "Which one? " + ", ".join(t.title for _, t in local[:4]) + ".")
    found = _match(hint, rows, lambda x: x[1].title)
    if len(found) == 1:
        return found[0]
    raise Stop(
        "clarify",
        "Which extension request? " + ", ".join(t.title for _, t in (found or rows)[:4]) + ".",
    )


# ----------------------------------------------------------------------------- one turn


@dataclass
class TurnRecord:
    result: TurnResult
    trace_id: uuid.UUID


def run_turn(
    db: Session,
    p: Principal,
    text: str,
    *,
    path: str | None,
    page_summary: str | None,
    channel: str,
    stt_ms: int | None = None,
) -> TurnRecord:
    t0 = time.perf_counter()
    intent = parse(text)
    steps: list[dict] = [{"step": "understood", "intent": intent.name, "slots": intent.slots}]
    pending = _open_pending(db, p)
    if pending:
        steps.append({"step": "pending_found", "tool": pending.tool, "awaiting": pending.awaiting})
    error = None
    pending_id = pending.id if pending else None

    try:
        # 1. Filling in a missing note / reason / date, then the next question or the read-back
        if pending and pending.awaiting and intent.name not in ("cancel", "confirm.no"):
            filled = pending.awaiting
            result = _fill(db, pending, text, intent)
            steps.append({"step": "slot_filled", "field": filled, "next": pending.awaiting})
            db.commit()

        # 2. Confirmation
        elif intent.name == "confirm.yes":
            if not pending or pending.awaiting:
                result = TurnResult(
                    intent, "unsupported", "There is nothing waiting for your confirmation."
                )
                db.commit()
            else:
                tool, args = pending.tool, dict(pending.args)
                try:
                    speech, replan_task = _execute(db, p, tool, args)
                    _close(db, pending, "executed")
                    db.commit()
                    steps.append({"step": "executed", "tool": tool})
                except DomainError as exc:
                    db.rollback()
                    stale = db.get(AgentPendingAction, pending_id)
                    if stale:
                        _close(db, stale, "failed")
                    db.commit()
                    steps.append({"step": "execution_refused", "code": exc.code})
                    raise Stop(
                        "failed", f"I couldn't do that: {exc.message} Nothing was changed."
                    ) from exc
                if replan_task:
                    orchestrator.reevaluate_after_task_change(db, replan_task)
                    steps.append({"step": "replanned"})
                result = TurnResult(intent, "done", speech, tool=tool)

        elif intent.name in ("confirm.no", "cancel"):
            if pending:
                _close(db, pending, "cancelled")
                db.commit()
                result = TurnResult(
                    intent, "ok", "Cancelled. Nothing was changed.", tool=pending.tool
                )
            else:
                result = safe_handle_text(db, p, text, path=path, page_summary=page_summary)

        # 3. A new change request: resolve, check, read back
        elif intent.name in CHANGE_TOOLS:
            proposal = _propose(db, p, intent, path)
            _supersede_all(db, p)
            new = AgentPendingAction(
                organization_id=p.organization_id,
                user_id=p.user_id,
                tool=proposal.tool,
                args=proposal.args,
                awaiting=proposal.awaiting,
                summary=proposal.summary,
                expires_at=utcnow() + PENDING_TTL,
            )
            db.add(new)
            db.flush()
            pending_id = new.id
            steps.append(
                {
                    "step": "proposed",
                    "tool": proposal.tool,
                    "awaiting": proposal.awaiting,
                    "checks": [c["text"] for c in proposal.checks],
                }
            )
            db.commit()
            result = _ask(proposal, intent, new.id)

        # 4. Navigation and read-only questions
        else:
            result = safe_handle_text(db, p, text, path=path, page_summary=page_summary)
            if pending and not pending.awaiting:
                result.speech = (
                    result.speech + " " if result.speech else ""
                ) + "Your earlier request is still waiting: say yes or cancel."
    except Stop as stop:
        db.rollback()
        result = stop.result
        result.intent = intent
        steps.append({"step": "stopped", "outcome": result.outcome})
    except DomainError as exc:
        db.rollback()
        error = exc.code
        result = TurnResult(intent, "denied", exc.message)

    trace = AgentTrace(
        organization_id=p.organization_id,
        user_id=p.user_id,
        channel=channel,
        transcript=text[:500],
        stt_ms=stt_ms,
        intent=intent.name,
        slots=intent.slots,
        tool=result.tool,
        pending_action_id=pending_id,
        outcome=result.outcome,
        steps=steps,
        speech=result.speech[:1000],
        error=error,
        total_ms=int((time.perf_counter() - t0) * 1000),
    )
    db.add(trace)
    db.commit()
    return TurnRecord(result, trace.id)
