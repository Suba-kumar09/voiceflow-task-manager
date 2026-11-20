"""Role and organization boundaries (CLAUDE.md Phase 2 acceptance criteria)."""

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditEvent, AuditOutcome
from tests.conftest import login

pytestmark = pytest.mark.integration


def roster(client, world, team_key):
    return client.get(f"/api/v1/teams/{world[team_key]}/employees")


def profile(client, world, user_key):
    return client.get(f"/api/v1/employees/{world[user_key]}")


# ------------------------------------------------------------------ team rosters


def test_manager_sees_own_team_roster(client, world):
    login(client, "manager_web")
    resp = roster(client, world, "team_web")
    assert resp.status_code == 200
    names = {e["display_name"] for e in resp.json()["items"]}
    assert names == {"Manager Web", "Emp Web 1", "Emp Web 2", "Inactive Emp"}
    assert resp.json()["total"] == 4


def test_roster_pagination(client, world):
    login(client, "manager_web")
    resp = client.get(f"/api/v1/teams/{world['team_web']}/employees?limit=2&offset=2")
    body = resp.json()
    assert body["total"] == 4 and body["limit"] == 2 and len(body["items"]) == 2


def test_manager_cannot_see_other_team_roster_and_denial_is_audited(client, world, db):
    login(client, "manager_web")
    resp = roster(client, world, "team_mobile")
    assert resp.status_code == 403
    denied = db.execute(
        select(AuditEvent).where(AuditEvent.outcome == AuditOutcome.DENIED)
    ).scalar_one()
    assert denied.action == "team.roster.view"
    assert denied.actor_user_id == world["manager_web"]
    assert denied.target_id == str(world["team_mobile"])


def test_employee_cannot_see_roster_of_own_team(client, world):
    login(client, "emp_web_1")
    assert roster(client, world, "team_web").status_code == 403


def test_admin_sees_every_team_in_own_org(client, world):
    login(client, "admin_a")
    assert roster(client, world, "team_web").status_code == 200
    assert roster(client, world, "team_mobile").status_code == 200


def test_other_organization_team_looks_nonexistent(client, world):
    login(client, "admin_a")
    resp = roster(client, world, "team_b")
    assert resp.status_code == 404
    assert resp.json()["error"]["message"] == "Team not found."


def test_unknown_team_is_404(client, world):
    login(client, "admin_a")
    assert client.get(f"/api/v1/teams/{uuid.uuid4()}/employees").status_code == 404


# ------------------------------------------------------------------ employee profiles


def test_employee_can_see_own_profile(client, world):
    login(client, "emp_web_1")
    resp = profile(client, world, "emp_web_1")
    assert resp.status_code == 200
    assert resp.json()["teams"][0]["team_name"] == "Web"


def test_employee_cannot_see_coworker_profile(client, world):
    login(client, "emp_web_1")
    assert profile(client, world, "emp_web_2").status_code == 403


def test_manager_sees_member_of_managed_team_only(client, world):
    login(client, "manager_web")
    assert profile(client, world, "emp_web_2").status_code == 200
    assert profile(client, world, "emp_mobile").status_code == 403


def test_manager_cannot_reach_other_organization(client, world):
    login(client, "manager_b")
    assert profile(client, world, "emp_web_1").status_code == 404
    assert roster(client, world, "team_web").status_code == 404


def test_endpoints_reject_anonymous_callers(client, world):
    assert roster(client, world, "team_web").status_code == 401
    assert profile(client, world, "emp_web_1").status_code == 401


def test_responses_never_include_secrets(client, world):
    login(client, "admin_a")
    for resp in (roster(client, world, "team_web"), profile(client, world, "emp_web_1")):
        text = resp.text.lower()
        assert "password" not in text and "argon2" not in text and "token_hash" not in text
