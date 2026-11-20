"""Create a clearly labelled DEMO organization for local development.

Usage (from backend/):
    python -m app.cli.seed_demo --credentials-file D:\\tools\\voiceflow-demo-logins.txt

Passwords are random and written only to the credentials file (never printed, never in git).
Refuses to run in production and does nothing if the demo organization already exists.
"""

import argparse
import secrets
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.core.config import get_settings
from app.db.session import get_engine
from app.models import (
    MembershipRole,
    Organization,
    Team,
    TeamMembership,
    User,
    UserRole,
)

DEMO_SLUG = "demo"

# (username, display name, role, team, membership role)
DEMO_PEOPLE = [
    ("demo.admin", "Demo Admin", UserRole.ADMIN, None, None),
    ("kavitha", "Kavitha", UserRole.MANAGER, "Web Platform", MembershipRole.MANAGER),
    ("subashini", "Subashini", UserRole.EMPLOYEE, "Web Platform", MembershipRole.MEMBER),
    ("priya", "Priya", UserRole.EMPLOYEE, "Web Platform", MembershipRole.MEMBER),
    ("arun", "Arun", UserRole.EMPLOYEE, "Web Platform", MembershipRole.MEMBER),
    ("meena", "Meena", UserRole.EMPLOYEE, "Web Platform", MembershipRole.MEMBER),
    ("ravi", "Ravi", UserRole.MANAGER, "Mobile", MembershipRole.MANAGER),
    ("deepak", "Deepak", UserRole.EMPLOYEE, "Mobile", MembershipRole.MEMBER),
]


def seed(db: Session, timezone: str) -> list[tuple[str, str, str]] | None:
    if db.execute(select(Organization).where(Organization.slug == DEMO_SLUG)).scalar_one_or_none():
        return None

    org = Organization(
        name="Demo Organization (DEMO DATA)", slug=DEMO_SLUG, timezone=timezone, is_demo=True
    )
    db.add(org)
    db.flush()

    teams: dict[str, Team] = {}
    for name in sorted({p[3] for p in DEMO_PEOPLE if p[3]}):
        teams[name] = Team(organization_id=org.id, name=name)
        db.add(teams[name])
    db.flush()

    credentials = []
    for username, display, role, team_name, membership in DEMO_PEOPLE:
        password = secrets.token_urlsafe(12)  # 16 characters
        user = User(
            organization_id=org.id,
            username=username,
            display_name=display,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.flush()
        if team_name and membership:
            db.add(
                TeamMembership(
                    team_id=teams[team_name].id, user_id=user.id, membership_role=membership
                )
            )
        credentials.append((username, role.value, password))
    db.commit()
    return credentials


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--credentials-file", required=True, type=Path)
    args = parser.parse_args()

    settings = get_settings()
    if settings.environment == "production":
        print("Refusing to seed demo data in production.", file=sys.stderr)
        return 2
    if args.credentials_file.exists():
        print(f"{args.credentials_file} already exists; not overwriting.", file=sys.stderr)
        return 2

    with Session(get_engine()) as db:
        creds = seed(db, settings.default_timezone)
    if creds is None:
        print("Demo organization already exists; nothing to do.")
        return 0

    lines = [
        "VoiceFlow DEMO accounts (local development only). Keep this file private.",
        "",
        f"{'username':<12} {'role':<9} password",
        *(f"{u:<12} {r:<9} {p}" for u, r, p in creds),
        "",
    ]
    args.credentials_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"Created {len(creds)} demo accounts. Logins written to {args.credentials_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
