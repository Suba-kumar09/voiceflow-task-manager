from app.services.orchestrator.backlog import BacklogItem, find_cycle, validate_backlog

KNOWN = {"python", "react", "ios"}
TEAM = {"python", "react"}


def item(key, deps=(), skills=(), title="Task", priority="HIGH"):
    return BacklogItem(key, title, priority, tuple(deps), tuple(skills))


def test_valid_backlog_gives_start_order_and_roots():
    r = validate_backlog(
        [item("T3", ["T1", "T2"]), item("T1"), item("T2", ["T1"]), item("T4")], KNOWN, TEAM
    )
    assert r.ok
    assert r.roots == ["T1", "T4"]
    assert r.order.index("T1") < r.order.index("T2") < r.order.index("T3")


def test_dependency_loop_is_reported_with_its_path():
    r = validate_backlog([item("T1", ["T3"]), item("T2", ["T1"]), item("T3", ["T2"])], KNOWN, TEAM)
    assert not r.ok
    assert len(r.errors) == 1
    msg = r.errors[0]
    assert msg.startswith("Dependency loop:")
    assert all(k in msg for k in ("T1", "T2", "T3"))


def test_find_cycle_returns_none_for_a_dag():
    assert find_cycle({"a": {"b"}, "b": set(), "c": {"a", "b"}}, ["a", "b", "c"]) is None


def test_every_problem_is_reported_at_once():
    r = validate_backlog(
        [
            item("T1", ["T9"]),  # unknown predecessor
            item("T1"),  # duplicate key
            item("T2", ["T2"]),  # depends on itself
            item("T3", title="  "),  # no title
            item("T4", priority=None),  # no priority: never guessed
            item("T5", priority="CRITICAL"),
            item("T6", skills=["Kotlin"]),  # not in the catalog
            item("", title="No key"),
        ],
        KNOWN,
        TEAM,
    )
    text = " | ".join(r.errors)
    for expected in (
        "depends on T9, which is not in the backlog",
        "Task ID T1 is used more than once",
        "T2 depends on itself",
        "T3 has no title",
        "T4 has priority None",
        "T5 has priority 'CRITICAL'",
        "“Kotlin”, which is not in the skill catalog",
        "has no task ID",
    ):
        assert expected in text, expected


def test_skill_nobody_on_the_team_has_is_a_warning_not_an_error():
    r = validate_backlog([item("T1", skills=["iOS"])], KNOWN, TEAM)
    assert r.ok
    assert "no one on the team has it yet" in r.warnings[0]


def test_empty_backlog_is_an_error():
    assert validate_backlog([], KNOWN, TEAM).errors == ["The backlog is empty."]
