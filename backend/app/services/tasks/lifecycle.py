"""Task lifecycle: the single transition table (CLAUDE.md section 9). Pure, no I/O.

Every state change goes through `rule_for(action)`. Anything not listed is refused.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.models import EvidencePolicy, TaskStatus

S = TaskStatus


class ActorKind(StrEnum):
    MANAGER = "MANAGER"  # administrator, or manager of the task's team
    ASSIGNEE = "ASSIGNEE"  # the employee currently holding the task
    SYSTEM = "SYSTEM"  # the deterministic orchestrator (Phase 4)


class Action(StrEnum):
    PUBLISH = "publish"
    ASSIGN = "assign"
    REASSIGN = "reassign"
    UNASSIGN = "unassign"
    ACCEPT = "accept"
    DECLINE = "decline"
    START = "start"
    BLOCK = "block"
    RESUME = "resume"
    REQUEST_COMPLETION = "request_completion"
    APPROVE_COMPLETION = "approve_completion"
    REJECT_COMPLETION = "reject_completion"
    CANCEL = "cancel"


# Sentinel target: request_completion goes to COMPLETED or PENDING_REVIEW depending on the task.
COMPLETION_TARGETS = frozenset({S.COMPLETED, S.PENDING_REVIEW})


@dataclass(frozen=True)
class Rule:
    from_statuses: frozenset[TaskStatus]
    to_statuses: frozenset[TaskStatus]
    actors: frozenset[ActorKind]
    reason_required: bool = False


def _r(frm, to, actors, reason=False) -> Rule:
    return Rule(frozenset(frm), frozenset(to), frozenset(actors), reason)


M, A, SYS = ActorKind.MANAGER, ActorKind.ASSIGNEE, ActorKind.SYSTEM

RULES: dict[Action, Rule] = {
    Action.PUBLISH: _r({S.DRAFT}, {S.UNASSIGNED}, {M}),
    Action.ASSIGN: _r({S.UNASSIGNED}, {S.ASSIGNED}, {M, SYS}),
    Action.REASSIGN: _r({S.ASSIGNED, S.ACCEPTED, S.BLOCKED}, {S.ASSIGNED}, {M}, reason=True),
    Action.UNASSIGN: _r({S.ASSIGNED, S.ACCEPTED, S.BLOCKED}, {S.UNASSIGNED}, {M}, reason=True),
    Action.ACCEPT: _r({S.ASSIGNED}, {S.ACCEPTED}, {A}),
    Action.DECLINE: _r({S.ASSIGNED}, {S.UNASSIGNED}, {A}, reason=True),
    Action.START: _r({S.ASSIGNED, S.ACCEPTED}, {S.IN_PROGRESS}, {A}),
    Action.BLOCK: _r({S.ASSIGNED, S.ACCEPTED, S.IN_PROGRESS}, {S.BLOCKED}, {A}, reason=True),
    Action.RESUME: _r({S.BLOCKED}, {S.IN_PROGRESS}, {A, M}),
    Action.REQUEST_COMPLETION: _r({S.IN_PROGRESS}, COMPLETION_TARGETS, {A}),
    Action.APPROVE_COMPLETION: _r({S.PENDING_REVIEW}, {S.COMPLETED}, {M}),
    Action.REJECT_COMPLETION: _r({S.PENDING_REVIEW}, {S.IN_PROGRESS}, {M}, reason=True),
    Action.CANCEL: _r({S.DRAFT, S.UNASSIGNED, S.ASSIGNED}, {S.CANCELLED}, {M}, reason=True),
}


class TransitionRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code  # "invalid_transition" | "forbidden" | "reason_required"
        self.message = message


def check(
    action: Action, current: TaskStatus, actor_kinds: set[ActorKind], reason: str | None
) -> Rule:
    """Validate an action. Raises TransitionRefused; returns the rule if allowed."""
    rule = RULES[action]
    if not actor_kinds & rule.actors:
        raise TransitionRefused("forbidden", f"You are not allowed to {action.value} this task.")
    if current not in rule.from_statuses:
        raise TransitionRefused(
            "invalid_transition",
            f"Cannot {action.value.replace('_', ' ')} a task that is {current.value}.",
        )
    if rule.reason_required and not (reason and reason.strip()):
        raise TransitionRefused("reason_required", f"A reason is required to {action.value}.")
    return rule


def needs_review(requires_approval: bool, evidence_policy: EvidencePolicy) -> bool:
    """A spoken "done" is a claim, not proof: anything with evidence or approval goes to review."""
    return requires_approval or evidence_policy is not EvidencePolicy.NONE


def completion_target(requires_approval: bool, evidence_policy: EvidencePolicy) -> TaskStatus:
    return S.PENDING_REVIEW if needs_review(requires_approval, evidence_policy) else S.COMPLETED


def allowed_edges() -> set[tuple[TaskStatus, TaskStatus]]:
    """Every (from, to) status pair the table permits — used to verify against CLAUDE.md."""
    return {(f, t) for rule in RULES.values() for f in rule.from_statuses for t in rule.to_statuses}
