"""Deterministic assignment planner (pure). The LLM never chooses who gets a task.

Rules (CLAUDE.md sections 4.3, 4.8, 9):
1. Only READY tasks: UNASSIGNED and every dependency COMPLETED (decided by the caller).
2. Tasks are ranked: priority (URGENT first), due date (soonest first, none last),
   created time, then backlog key — fully deterministic.
3. A person qualifies if they hold ALL required skills and are below their workload limit.
4. Among qualified people: lowest current load, then fewest tasks already given in this
   project (fairness), then longest since their last assignment, then id.
5. High priority never overrides an unmet dependency or a missing skill.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

PRIORITY_RANK = {"URGENT": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_FAR_FUTURE = datetime(9999, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class ReadyTask:
    id: uuid.UUID
    key: str
    title: str
    priority: str
    due_at: datetime | None
    created_at: datetime
    required_skills: frozenset[str] = frozenset()
    excluded: frozenset[uuid.UUID] = frozenset()  # e.g. people who declined this task


@dataclass
class Candidate:
    id: uuid.UUID
    name: str
    skills: frozenset[str]
    load: int
    wip_limit: int
    assigned_in_project: int = 0
    last_assigned_at: datetime | None = None


class Outcome(StrEnum):
    ASSIGN = "ASSIGN"
    NO_CAPACITY = "NO_CAPACITY"  # qualified people exist but are all at their limit
    NO_QUALIFIED = "NO_QUALIFIED"  # nobody on the team has the skills: needs a manager


@dataclass(frozen=True)
class PlanItem:
    task: ReadyTask
    outcome: Outcome
    assignee: Candidate | None
    reason: str


@dataclass
class Plan:
    items: list[PlanItem] = field(default_factory=list)

    @property
    def assignments(self) -> list[PlanItem]:
        return [i for i in self.items if i.outcome is Outcome.ASSIGN]

    @property
    def needs_decision(self) -> list[PlanItem]:
        return [i for i in self.items if i.outcome is Outcome.NO_QUALIFIED]


def rank_tasks(tasks: list[ReadyTask]) -> list[ReadyTask]:
    return sorted(
        tasks,
        key=lambda t: (
            -PRIORITY_RANK.get(t.priority, 0),
            t.due_at or _FAR_FUTURE,
            t.created_at,
            t.key,
            str(t.id),
        ),
    )


def _skills_text(skills: frozenset[str]) -> str:
    return ", ".join(sorted(skills)) if skills else "no special skills"


def plan_assignments(tasks: list[ReadyTask], people: list[Candidate]) -> Plan:
    plan = Plan()
    pool = {p.id: Candidate(**vars(p)) for p in people}  # copies: loads change as we plan
    for task in rank_tasks(tasks):
        has_skills = [p for p in pool.values() if task.required_skills <= p.skills]
        skilled = [p for p in has_skills if p.id not in task.excluded]
        if not skilled:
            reason = (
                f"Everyone with {_skills_text(task.required_skills)} has declined this task."
                if has_skills
                else f"No one on the team has {_skills_text(task.required_skills)}."
            )
            plan.items.append(PlanItem(task, Outcome.NO_QUALIFIED, None, reason))
            continue
        free = [p for p in skilled if p.load < p.wip_limit]
        if not free:
            plan.items.append(
                PlanItem(
                    task,
                    Outcome.NO_CAPACITY,
                    None,
                    "Everyone with "
                    f"{_skills_text(task.required_skills)} is at their workload limit.",
                )
            )
            continue
        best = min(
            free,
            key=lambda p: (
                p.load,
                p.assigned_in_project,
                p.last_assigned_at or _EPOCH,
                str(p.id),
            ),
        )
        reason = (
            f"Needs {_skills_text(task.required_skills)}; {best.name} has "
            + ("no active task" if best.load == 0 else f"{best.load} of {best.wip_limit} active")
            + "."
        )
        plan.items.append(PlanItem(task, Outcome.ASSIGN, best, reason))
        best.load += 1
        best.assigned_in_project += 1
        best.last_assigned_at = _FAR_FUTURE  # just assigned: go to the back of the queue
    return plan
