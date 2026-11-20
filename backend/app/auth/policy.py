"""Authorization policy: every access decision lives here, as pure, testable functions.

Rules (CLAUDE.md section 3):
- Everything is scoped to the caller's organization.
- Administrators may see all teams and users in their organization.
- Managers may see the teams they manage and the members of those teams.
- Employees may see only themselves.
"""

import uuid
from collections.abc import Iterable
from enum import StrEnum

from app.auth.principal import Principal


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"  # visible to the caller's organization, but not permitted -> 403
    NOT_FOUND = "NOT_FOUND"  # other organization: do not reveal it exists -> 404


def can_view_team_roster(p: Principal, team_org_id: uuid.UUID, team_id: uuid.UUID) -> Decision:
    if team_org_id != p.organization_id:
        return Decision.NOT_FOUND
    if p.is_admin or team_id in p.managed_team_ids:
        return Decision.ALLOW
    return Decision.DENY


def can_view_employee(
    p: Principal,
    target_user_id: uuid.UUID,
    target_org_id: uuid.UUID,
    target_team_ids: Iterable[uuid.UUID],
) -> Decision:
    if target_org_id != p.organization_id:
        return Decision.NOT_FOUND
    if p.is_admin or target_user_id == p.user_id:
        return Decision.ALLOW
    if p.managed_team_ids.intersection(target_team_ids):
        return Decision.ALLOW
    return Decision.DENY
