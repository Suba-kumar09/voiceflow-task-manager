import uuid

from app.auth.policy import Decision, can_view_employee, can_view_team_roster
from app.auth.principal import Principal
from app.models import UserRole

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()
TEAM_WEB = uuid.uuid4()
TEAM_MOBILE = uuid.uuid4()


def principal(role: UserRole, managed=(), member=(), user_id=None) -> Principal:
    return Principal(
        user_id=user_id or uuid.uuid4(),
        organization_id=ORG,
        role=role,
        session_id=uuid.uuid4(),
        csrf_token="x",
        member_team_ids=frozenset(member) | frozenset(managed),
        managed_team_ids=frozenset(managed),
    )


class TestTeamRoster:
    def test_manager_sees_own_team(self):
        p = principal(UserRole.MANAGER, managed=[TEAM_WEB])
        assert can_view_team_roster(p, ORG, TEAM_WEB) is Decision.ALLOW

    def test_manager_denied_other_team(self):
        p = principal(UserRole.MANAGER, managed=[TEAM_WEB])
        assert can_view_team_roster(p, ORG, TEAM_MOBILE) is Decision.DENY

    def test_employee_denied_even_own_team(self):
        p = principal(UserRole.EMPLOYEE, member=[TEAM_WEB])
        assert can_view_team_roster(p, ORG, TEAM_WEB) is Decision.DENY

    def test_admin_sees_any_team_in_org(self):
        assert can_view_team_roster(principal(UserRole.ADMIN), ORG, TEAM_MOBILE) is Decision.ALLOW

    def test_other_organization_is_not_found_even_for_admin(self):
        p = principal(UserRole.ADMIN)
        assert can_view_team_roster(p, OTHER_ORG, uuid.uuid4()) is Decision.NOT_FOUND


class TestEmployeeProfile:
    def test_employee_sees_self(self):
        me = uuid.uuid4()
        p = principal(UserRole.EMPLOYEE, member=[TEAM_WEB], user_id=me)
        assert can_view_employee(p, me, ORG, [TEAM_WEB]) is Decision.ALLOW

    def test_employee_denied_coworker(self):
        p = principal(UserRole.EMPLOYEE, member=[TEAM_WEB])
        assert can_view_employee(p, uuid.uuid4(), ORG, [TEAM_WEB]) is Decision.DENY

    def test_manager_sees_member_of_managed_team(self):
        p = principal(UserRole.MANAGER, managed=[TEAM_WEB])
        assert can_view_employee(p, uuid.uuid4(), ORG, [TEAM_WEB]) is Decision.ALLOW

    def test_manager_denied_member_of_other_team(self):
        p = principal(UserRole.MANAGER, managed=[TEAM_WEB])
        assert can_view_employee(p, uuid.uuid4(), ORG, [TEAM_MOBILE]) is Decision.DENY

    def test_manager_denied_employee_with_no_team(self):
        p = principal(UserRole.MANAGER, managed=[TEAM_WEB])
        assert can_view_employee(p, uuid.uuid4(), ORG, []) is Decision.DENY

    def test_other_organization_is_not_found(self):
        p = principal(UserRole.ADMIN)
        assert can_view_employee(p, uuid.uuid4(), OTHER_ORG, []) is Decision.NOT_FOUND
