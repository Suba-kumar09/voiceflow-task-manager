"""Add a few DEMO tasks to the demo organization (run after seed_demo).

Usage (from backend/):  python -m app.cli.seed_demo_tasks

Goes through the task service, so demo data obeys the same rules, history and audit as real use.
Does nothing if the demo tasks already exist. Refuses to run in production.
"""

import sys
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.principal import Principal
from app.core.config import get_settings
from app.db.session import get_engine
from app.models import (
    MembershipRole,
    Organization,
    Task,
    TaskPriority,
    Team,
    TeamMembership,
    User,
)
from app.models.common import utcnow
from app.services.tasks import service
from app.services.tasks.lifecycle import Action

DEMO_MARK = "[DEMO] "


def _principal(db: Session, username: str) -> Principal:
    user = db.execute(select(User).where(User.username == username)).scalar_one()
    rows = db.execute(
        select(TeamMembership.team_id, TeamMembership.membership_role).where(
            TeamMembership.user_id == user.id
        )
    ).all()
    return Principal(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        session_id=user.id,  # not a real session: CLI actor
        csrf_token="cli",  # noqa: S106 - placeholder; a CLI actor has no browser session
        member_team_ids=frozenset(t for t, _ in rows),
        managed_team_ids=frozenset(t for t, r in rows if r is MembershipRole.MANAGER),
    )


def main() -> int:
    if get_settings().environment == "production":
        print("Refusing to seed demo data in production.", file=sys.stderr)
        return 2
    with Session(get_engine(), expire_on_commit=False) as db:
        org = db.execute(
            select(Organization).where(Organization.slug == "demo")
        ).scalar_one_or_none()
        if org is None or not org.is_demo:
            print("Run `python -m app.cli.seed_demo` first.", file=sys.stderr)
            return 2
        if db.execute(select(Task.id).where(Task.organization_id == org.id).limit(1)).first():
            print("Demo tasks already exist; nothing to do.")
            return 0

        web = db.execute(
            select(Team).where(Team.organization_id == org.id, Team.name == "Web Platform")
        ).scalar_one()
        kavitha = _principal(db, "kavitha")
        user_id = {
            u.username: u.id
            for u in db.execute(select(User).where(User.organization_id == org.id)).scalars()
        }
        now = utcnow()

        def create(title, priority, days, criteria="", policy=None):
            data = service.NewTask(
                team_id=web.id,
                title=DEMO_MARK + title,
                priority=priority,
                due_at=now + timedelta(days=days),
                acceptance_criteria=criteria,
                **({"evidence_policy": policy} if policy else {}),
            )
            return service.create_task(db, kavitha, data)

        testing = create(
            "Website testing", TaskPriority.HIGH, 1, "All checkout pages pass on Chrome and Edge."
        )
        service.assign_task(db, kavitha, testing.id, user_id["subashini"])
        service.transition(db, _principal(db, "subashini"), testing.id, Action.START)

        checkout = create(
            "Checkout page UI", TaskPriority.MEDIUM, 4, "Matches the approved design."
        )
        service.assign_task(db, kavitha, checkout.id, user_id["priya"])

        create("API testing", TaskPriority.HIGH, 3, "Every endpoint has a passing test.")
        create("Update privacy policy text", TaskPriority.LOW, 10)
        db.commit()
    print("Created 4 demo tasks for the Web Platform team.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
