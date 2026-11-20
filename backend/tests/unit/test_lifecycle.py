import pytest

from app.models import EvidencePolicy, TaskStatus
from app.services.tasks import lifecycle
from app.services.tasks.lifecycle import RULES, Action, ActorKind, TransitionRefused

S = TaskStatus
M, A, SYS = ActorKind.MANAGER, ActorKind.ASSIGNEE, ActorKind.SYSTEM


def test_every_action_has_a_rule():
    assert set(RULES) == set(Action)


def test_transition_table_matches_claude_md_section_9():
    edges = lifecycle.allowed_edges()
    # Main path
    for edge in [
        (S.DRAFT, S.UNASSIGNED),
        (S.UNASSIGNED, S.ASSIGNED),
        (S.ASSIGNED, S.ACCEPTED),
        (S.ACCEPTED, S.IN_PROGRESS),
        (S.IN_PROGRESS, S.PENDING_REVIEW),
        (S.PENDING_REVIEW, S.COMPLETED),
    ]:
        assert edge in edges, edge
    # Other transitions listed in the spec
    for edge in [
        (S.ASSIGNED, S.BLOCKED),
        (S.ACCEPTED, S.BLOCKED),
        (S.IN_PROGRESS, S.BLOCKED),
        (S.BLOCKED, S.IN_PROGRESS),
        (S.UNASSIGNED, S.CANCELLED),
        (S.ASSIGNED, S.CANCELLED),
        (S.PENDING_REVIEW, S.IN_PROGRESS),
    ]:
        assert edge in edges, edge


@pytest.mark.parametrize(
    "edge",
    [
        (S.COMPLETED, S.IN_PROGRESS),  # completed is final
        (S.CANCELLED, S.UNASSIGNED),  # cancelled is final
        (S.UNASSIGNED, S.IN_PROGRESS),  # cannot start without an owner
        (S.UNASSIGNED, S.COMPLETED),  # cannot complete unowned work
        (S.ASSIGNED, S.COMPLETED),  # cannot skip doing the work
        (S.IN_PROGRESS, S.CANCELLED),  # spec: cancel only before work starts
        (S.BLOCKED, S.COMPLETED),
    ],
)
def test_forbidden_edges(edge):
    assert edge not in lifecycle.allowed_edges()


def test_final_statuses_have_no_way_out():
    for frm, _ in lifecycle.allowed_edges():
        assert frm not in (S.COMPLETED, S.CANCELLED)


@pytest.mark.parametrize(
    ("action", "status", "actors"),
    [
        (Action.START, S.ASSIGNED, {M}),  # a manager cannot start an employee's work
        (Action.REQUEST_COMPLETION, S.IN_PROGRESS, {M}),  # nor claim it is done
        (Action.APPROVE_COMPLETION, S.PENDING_REVIEW, {A}),  # employees cannot self-approve
        (Action.ASSIGN, S.UNASSIGNED, {A}),
        (Action.CANCEL, S.ASSIGNED, {A}),
    ],
)
def test_wrong_actor_is_refused(action, status, actors):
    with pytest.raises(TransitionRefused) as exc:
        lifecycle.check(action, status, actors, reason="because")
    assert exc.value.code == "forbidden"


def test_orchestrator_may_assign_but_nothing_else():
    lifecycle.check(Action.ASSIGN, S.UNASSIGNED, {SYS}, None)
    for action in Action:
        if action is not Action.ASSIGN:
            assert SYS not in RULES[action].actors, action


def test_wrong_status_is_invalid_transition():
    with pytest.raises(TransitionRefused) as exc:
        lifecycle.check(Action.START, S.UNASSIGNED, {A}, None)
    assert exc.value.code == "invalid_transition"


@pytest.mark.parametrize(
    "action",
    [a for a, r in RULES.items() if r.reason_required],
)
def test_reason_required_actions_reject_blank_reason(action):
    rule = RULES[action]
    status = next(iter(rule.from_statuses))
    actor = next(iter(rule.actors))
    for blank in (None, "", "   "):
        with pytest.raises(TransitionRefused) as exc:
            lifecycle.check(action, status, {actor}, blank)
        assert exc.value.code == "reason_required"


def test_reason_required_for_the_right_actions():
    needs_reason = {a for a, r in RULES.items() if r.reason_required}
    assert needs_reason == {
        Action.REASSIGN,
        Action.UNASSIGN,
        Action.DECLINE,
        Action.BLOCK,
        Action.REJECT_COMPLETION,
        Action.CANCEL,
    }


@pytest.mark.parametrize(
    ("requires_approval", "policy", "expected"),
    [
        (False, EvidencePolicy.NONE, S.COMPLETED),
        (True, EvidencePolicy.NONE, S.PENDING_REVIEW),
        (False, EvidencePolicy.NOTE, S.PENDING_REVIEW),
        (False, EvidencePolicy.LINK, S.PENDING_REVIEW),
        (False, EvidencePolicy.MANAGER_APPROVAL, S.PENDING_REVIEW),
    ],
)
def test_spoken_done_is_a_claim_not_proof(requires_approval, policy, expected):
    assert lifecycle.completion_target(requires_approval, policy) is expected
