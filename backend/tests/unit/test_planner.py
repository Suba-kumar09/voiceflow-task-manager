import random
import uuid
from datetime import UTC, datetime, timedelta

from app.services.orchestrator.planner import (
    Candidate,
    Outcome,
    ReadyTask,
    plan_assignments,
    rank_tasks,
)

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def task(key, priority="MEDIUM", skills=(), due=None, created=0, excluded=()):
    return ReadyTask(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, key),
        key=key,
        title=f"Task {key}",
        priority=priority,
        due_at=due,
        created_at=T0 + timedelta(minutes=created),
        required_skills=frozenset(skills),
        excluded=frozenset(excluded),
    )


def person(name, skills=(), load=0, wip=1, assigned=0, last=None):
    return Candidate(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, name),
        name=name,
        skills=frozenset(skills),
        load=load,
        wip_limit=wip,
        assigned_in_project=assigned,
        last_assigned_at=last,
    )


def who(plan):
    return {i.task.key: (i.assignee.name if i.assignee else i.outcome.value) for i in plan.items}


def test_ranking_priority_then_due_then_age_then_key():
    soon, late = T0 + timedelta(days=1), T0 + timedelta(days=5)
    tasks = [
        task("A", "LOW"),
        task("B", "HIGH", due=late),
        task("C", "HIGH", due=soon),
        task("D", "URGENT"),
        task("E", "HIGH"),  # no due date: after dated HIGH tasks
        task("F", "MEDIUM", created=5),
        task("G", "MEDIUM", created=1),
    ]
    assert [t.key for t in rank_tasks(tasks)] == ["D", "C", "B", "E", "G", "F", "A"]


def test_independent_tasks_go_to_different_people_in_parallel():
    plan = plan_assignments(
        [task("T1", "HIGH", ["python"]), task("T2", "HIGH", ["react"])],
        [person("Arun", ["python"]), person("Priya", ["react"])],
    )
    assert who(plan) == {"T1": "Arun", "T2": "Priya"}


def test_all_required_skills_must_be_held():
    plan = plan_assignments(
        [task("T1", skills=["react", "testing"])],
        [person("Priya", ["react"]), person("Subashini", ["react", "testing"])],
    )
    assert who(plan) == {"T1": "Subashini"}


def test_high_priority_wins_the_only_free_person():
    plan = plan_assignments(
        [task("low", "LOW", ["python"]), task("high", "HIGH", ["python"])],
        [person("Arun", ["python"])],
    )
    assert who(plan) == {"high": "Arun", "low": "NO_CAPACITY"}


def test_workload_limit_respected_and_load_counts_within_one_plan():
    plan = plan_assignments(
        [task("T1", "HIGH"), task("T2", "HIGH", created=1), task("T3", "HIGH", created=2)],
        [person("Priya", wip=2, load=0), person("Karthik", wip=1, load=1)],
    )
    assert who(plan) == {"T1": "Priya", "T2": "Priya", "T3": "NO_CAPACITY"}


def test_prefers_lowest_load_then_fairness_then_longest_wait():
    plan = plan_assignments(
        [task("T1")],
        [person("Busy", load=1, wip=3), person("Idle", load=0, wip=3)],
    )
    assert who(plan) == {"T1": "Idle"}

    plan = plan_assignments(
        [task("T1")],
        [person("Had3", assigned=3), person("Had1", assigned=1)],
    )
    assert who(plan) == {"T1": "Had1"}

    plan = plan_assignments(
        [task("T1")],
        [person("Recent", last=T0 + timedelta(days=2)), person("LongAgo", last=T0)],
    )
    assert who(plan) == {"T1": "LongAgo"}


def test_no_one_with_the_skill_needs_a_manager_decision():
    plan = plan_assignments([task("ios", skills=["ios"])], [person("Arun", ["python"])])
    item = plan.items[0]
    assert item.outcome is Outcome.NO_QUALIFIED
    assert item.reason == "No one on the team has ios."
    assert plan.needs_decision == [item]


def test_people_who_declined_are_skipped():
    arun = person("Arun", ["python"])
    plan = plan_assignments(
        [task("T1", skills=["python"], excluded=[arun.id])],
        [arun, person("Priya", ["python"])],
    )
    assert who(plan) == {"T1": "Priya"}

    plan = plan_assignments([task("T1", skills=["python"], excluded=[arun.id])], [arun])
    assert plan.items[0].outcome is Outcome.NO_QUALIFIED
    assert "declined" in plan.items[0].reason


def test_plan_is_deterministic_regardless_of_input_order():
    tasks = [task(f"T{i}", random.choice(["LOW", "HIGH"]), created=i) for i in range(12)]
    people = [person(f"P{i}", wip=2) for i in range(4)]
    expected = who(plan_assignments(tasks, people))
    for _ in range(5):
        random.shuffle(tasks)
        random.shuffle(people)
        assert who(plan_assignments(tasks, people)) == expected


def test_planner_does_not_mutate_input_candidates():
    p = person("Arun", wip=2)
    plan_assignments([task("T1")], [p])
    assert p.load == 0 and p.assigned_in_project == 0
