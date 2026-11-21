"""Turn a parsed intent into an action + a grounded spoken reply.

Everything spoken comes from authorized database reads through the normal services; nothing
is invented. Phase 6 only navigates and answers questions; it never changes data.
"""

import difflib
import re
import uuid
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.agent.intents import Intent, parse
from app.auth.principal import Principal
from app.models import ProjectStatus, Task
from app.services import notifications as notes
from app.services import projects as project_svc
from app.services import reports
from app.services.errors import DomainError
from app.services.tasks import service as task_svc

_PROJECT_PATH = re.compile(r"^/projects/([0-9a-f-]{36})")
_PRIORITY_WORD = {"URGENT": "urgent", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}


@dataclass
class TurnResult:
    intent: Intent
    outcome: str  # ok | clarify | repeat | unsupported | not_yet | denied
    speech: str
    action: dict | None = None
    suggestions: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)  # [{"text", "state": ok|warn|fail}]
    plan: list[dict] = field(default_factory=list)  # assignment plan read back to a manager
    awaiting_confirmation: bool = False
    tool: str | None = None


def _compact(s: str) -> str:
    s = s.lower().replace("[demo]", "")
    # Drop words people leave out when speaking ("the E-Commerce project" for
    # "E-Commerce Application Development"). "app" is kept: it distinguishes projects.
    s = re.sub(r"\b(?:the|project|application|development)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def resolve_project(db: Session, p: Principal, query: str):
    """Match a spoken project name against the caller's VISIBLE projects only.
    Returns (project | None, ambiguous_candidates)."""
    projects = project_svc.list_projects(db, p)
    q = _compact(query)
    if not q:
        return None, []
    exact = [x for x in projects if _compact(x.name) == q]
    if len(exact) == 1:
        return exact[0], []
    contains = [x for x in projects if q in _compact(x.name) or _compact(x.name) in q]
    if len(contains) == 1:
        return contains[0], []
    if len(contains) > 1:
        return None, contains
    scored = sorted(
        ((difflib.SequenceMatcher(None, q, _compact(x.name)).ratio(), x) for x in projects),
        key=lambda s: -s[0],
    )
    good = [x for score, x in scored if score >= 0.75]
    if len(good) == 1:
        return good[0], []
    return None, good


def _display(name: str) -> str:
    return name.replace("[DEMO] ", "")


def _spoken_due(task: Task) -> str:
    if not task.due_at:
        return ""
    local = task.due_at.astimezone(ZoneInfo(task.timezone))
    hour = local.strftime("%I:%M %p").lstrip("0").replace(":00", "")
    return f", due {local.strftime('%A')} {local.day} {local.strftime('%B')} at {hour}"


def _current_project_id(path: str | None) -> uuid.UUID | None:
    m = _PROJECT_PATH.match(path or "")
    return uuid.UUID(m.group(1)) if m else None


def _project_route(project_id, tab: str | None) -> str:
    return f"/projects/{project_id}" + (f"?tab={tab}" if tab and tab != "overview" else "")


def _is_manager(p: Principal) -> bool:
    return p.is_admin or bool(p.managed_team_ids)


def _help(p: Principal) -> str:
    if _is_manager(p):
        return (
            "You can say: give me today's summary, who has overdue tasks, who is overloaded, "
            "open the E-Commerce project, what is still pending, approve it, "
            "assign the ready tasks, read my notifications, or go back."
        )
    return (
        "You can say: what's my task, read my notifications, open my work, "
        "read this page, or go back."
    )


def _which_project(p: Principal, db: Session, candidates=None) -> TurnResult:
    options = candidates or project_svc.list_projects(db, p)
    names = [_display(x.name) for x in options][:5]
    return TurnResult(
        Intent("clarify.project"),
        "clarify",
        "Which project? "
        + ("You have: " + ", ".join(names) + "." if names else "You have no projects yet."),
        suggestions=[f"Open {n}" for n in names[:3]],
    )


def _pending_speech(prog: dict) -> str:
    parts = [f"{_display(prog['name'])}: {prog['completed']} of {prog['total']} tasks are done."]
    detail = []
    for key, label in (
        ("in_progress", "in progress"),
        ("ready_to_assign", "ready to assign"),
        ("waiting_on_dependencies", "waiting on other tasks"),
        ("blocked_by_issue", "blocked"),
        ("awaiting_review", "awaiting review"),
    ):
        if prog[key]:
            detail.append(f"{prog[key]} {label}")
    if detail:
        parts.append(
            ", ".join(detail[:-1]) + (" and " if len(detail) > 1 else "") + detail[-1] + "."
        )
    decisions = prog["needs_decision"]
    if decisions:
        parts.append(
            f"{len(decisions)} need{'s' if len(decisions) == 1 else ''} your decision: "
            + ", ".join(d["title"] for d in decisions[:3])
            + "."
        )
    return " ".join(parts)


def handle_text(
    db: Session, p: Principal, text: str, *, path: str | None, page_summary: str | None
) -> TurnResult:
    intent = parse(text)
    name = intent.name
    manager = _is_manager(p)

    if name == "empty":
        return TurnResult(intent, "repeat", "I didn't catch that. Please say it again.")
    if name == "cancel":
        return TurnResult(intent, "ok", "Okay.", {"type": "stop"})
    if name == "repeat":
        return TurnResult(intent, "ok", "", {"type": "repeat"})
    if name == "help":
        return TurnResult(intent, "ok", _help(p))
    if name == "unknown":
        return TurnResult(intent, "unsupported", "Sorry, I can't do that yet. " + _help(p))
    if name == "change.not_yet":
        return TurnResult(
            intent,
            "not_yet",
            "I can't make changes by voice yet. Please use the buttons on screen for now; "
            "voice actions with confirmation are coming next.",
        )

    # ---- navigation ----
    if name == "nav.back":
        return TurnResult(intent, "ok", "Going back.", {"type": "back"})
    if name == "nav.home":
        return TurnResult(intent, "ok", "Going home.", {"type": "navigate", "to": "/"})
    if name == "nav.my_work":
        if manager and not p.member_team_ids - p.managed_team_ids:
            return TurnResult(
                intent, "ok", "Opening your projects.", {"type": "navigate", "to": "/projects"}
            )
        return TurnResult(
            intent, "ok", "Opening your work.", {"type": "navigate", "to": "/my-work"}
        )
    if name == "nav.notifications":
        return TurnResult(
            intent, "ok", "Opening notifications.", {"type": "navigate", "to": "/notifications"}
        )
    if name == "nav.settings":
        return TurnResult(
            intent, "ok", "Opening settings.", {"type": "navigate", "to": "/settings"}
        )
    if name == "nav.traces":
        if not p.is_admin:
            return TurnResult(intent, "denied", "Voice traces are for administrators.")
        return TurnResult(
            intent, "ok", "Opening voice traces.", {"type": "navigate", "to": "/traces"}
        )
    if name == "nav.system":
        return TurnResult(
            intent, "ok", "Opening system status.", {"type": "navigate", "to": "/system"}
        )
    if name in ("nav.projects", "nav.team"):
        if not manager:
            return TurnResult(intent, "denied", "That page is for managers. " + _help(p))
        to = "/projects" if name == "nav.projects" else "/team"
        return TurnResult(
            intent,
            "ok",
            f"Opening {'projects' if to == '/projects' else 'the team page'}.",
            {"type": "navigate", "to": to},
        )

    if name == "nav.project_tab":
        tab = intent.slots["tab"]
        pid = _current_project_id(path)
        if pid is None:
            if tab == "tasks" and not manager:
                return TurnResult(
                    intent, "ok", "Opening your work.", {"type": "navigate", "to": "/my-work"}
                )
            return _which_project(p, db)
        if tab == "team" and not manager:
            return TurnResult(intent, "denied", "Only managers can see the team’s workload.")
        label = {"team": "the project team", "tasks": "the tasks", "overview": "the overview"}[tab]
        return TurnResult(
            intent, "ok", f"Showing {label}.", {"type": "navigate", "to": _project_route(pid, tab)}
        )

    if name == "nav.project":
        project, ambiguous = resolve_project(db, p, intent.slots["project"])
        if project is None:
            if ambiguous:
                return _which_project(p, db, ambiguous)
            names = [_display(x.name) for x in project_svc.list_projects(db, p)][:5]
            return TurnResult(
                intent,
                "clarify",
                f"I couldn't find a project called {intent.slots['project']}. "
                + (
                    "Your projects are: " + ", ".join(names) + "."
                    if names
                    else "You have no projects."
                ),
                suggestions=[f"Open {n}" for n in names[:3]],
            )
        tab = intent.slots.get("tab")
        if tab == "team" and not manager:
            return TurnResult(intent, "denied", "Only managers can see the team’s workload.")
        prog = project_svc.progress(db, p, project.id)
        speech = (
            f"Opening {_display(project.name)}. "
            f"{prog['completed']} of {prog['total']} tasks are done."
        )
        if tab == "team":
            speech = f"Showing the {_display(project.name)} team."
        elif tab == "tasks":
            speech = f"Showing the {_display(project.name)} tasks."
        return TurnResult(
            intent, "ok", speech, {"type": "navigate", "to": _project_route(project.id, tab)}
        )

    # ---- read-only questions ----
    if name == "query.my_task":
        task = task_svc.current_task(db, p)
        if task is None:
            return TurnResult(
                intent, "ok", "You have no active task right now. I'll tell you when one is ready."
            )
        state = {
            "IN_PROGRESS": "in progress",
            "ASSIGNED": "new",
            "ACCEPTED": "accepted",
            "BLOCKED": "blocked",
        }.get(task.status.value, task.status.value.lower())
        priority = _PRIORITY_WORD[task.priority.value]
        speech = (
            f"Your current task is {task.title}. "
            f"It is {state}, {priority} priority{_spoken_due(task)}."
        )
        if task.acceptance_criteria:
            speech += f" It is done when: {task.acceptance_criteria}"
        return TurnResult(intent, "ok", speech, {"type": "navigate", "to": "/my-work"})

    if name == "query.notifications":
        rows, _total, unread = notes.list_for(db, p.user_id, unread_only=True, limit=3, offset=0)
        if not unread:
            return TurnResult(
                intent,
                "ok",
                "You have no new notifications.",
                {"type": "navigate", "to": "/notifications"},
            )
        speech = f"You have {unread} new notification{'s' if unread != 1 else ''}. " + " ".join(
            f"{n.title}." for n in rows
        )
        return TurnResult(intent, "ok", speech, {"type": "navigate", "to": "/notifications"})

    if name == "query.pending":
        project = None
        if intent.slots.get("project"):
            project, ambiguous = resolve_project(db, p, intent.slots["project"])
            if project is None:
                return _which_project(p, db, ambiguous or None)
        else:
            pid = _current_project_id(path)
            if pid is not None:
                project = project_svc.load_project(db, p, pid, manage=False)
            else:
                active = [
                    x for x in project_svc.list_projects(db, p) if x.status is ProjectStatus.ACTIVE
                ]
                if len(active) != 1:
                    return _which_project(p, db, active or None)
                project = active[0]
        prog = project_svc.progress(db, p, project.id)
        return TurnResult(
            intent,
            "ok",
            _pending_speech(prog),
            {"type": "navigate", "to": _project_route(project.id, None)},
        )

    if name in ("query.summary", "query.overdue", "query.workload", "query.completed"):
        if not manager:
            return TurnResult(intent, "denied", "Team reports are for managers. " + _help(p))
        s = reports.summary(db, p, intent.slots.get("period", "today"))
        speech = {
            "query.summary": reports.summary_speech,
            "query.overdue": reports.overdue_speech,
            "query.workload": reports.workload_speech,
            "query.completed": reports.completed_speech,
        }[name](s)
        return TurnResult(intent, "ok", speech)

    if name == "read_page":
        if page_summary and page_summary.strip():
            return TurnResult(intent, "ok", page_summary.strip()[:600])
        return TurnResult(intent, "ok", "This page has no summary yet.")

    return TurnResult(intent, "unsupported", "Sorry, I can't do that yet. " + _help(p))


def safe_handle_text(
    db: Session, p: Principal, text: str, *, path: str | None, page_summary: str | None
) -> TurnResult:
    """Domain errors (e.g. no access to a project) become a spoken answer, not a crash."""
    try:
        return handle_text(db, p, text, path=path, page_summary=page_summary)
    except DomainError as exc:
        db.rollback()
        return TurnResult(parse(text), "denied", exc.message)
