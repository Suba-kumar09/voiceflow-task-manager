"""Create the [DEMO] E-Commerce project: skills, a 12-task backlog with dependencies, then
approve and start it so the orchestrator assigns real work. Run after seed_demo.

Usage (from backend/):  python -m app.cli.seed_demo_project

Goes through the same services as the API. Does nothing if the project already exists.
"""

import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli.seed_demo_tasks import _principal
from app.core.config import get_settings
from app.db.session import get_engine
from app.models import Organization, Project, Skill, Team, User
from app.services import projects as svc

NAME = "[DEMO] E-Commerce Application Development"

SKILLS = {
    "arun": ["Python", "APIs", "PostgreSQL"],
    "priya": ["React", "APIs", "Python"],
    "subashini": ["Testing", "React"],
    "meena": ["Design"],
}

T = svc.BacklogTaskIn
BACKLOG = [
    T(
        "EC01",
        "Requirements & database schema",
        "HIGH",
        required_skills=("PostgreSQL",),
        acceptance_criteria="Schema for products, carts and orders is reviewed.",
    ),
    T(
        "EC02",
        "UI design mockups",
        "HIGH",
        required_skills=("Design",),
        acceptance_criteria="All checkout screens designed and approved.",
        requires_approval=True,
    ),
    T(
        "EC03",
        "Product catalog API",
        "HIGH",
        required_skills=("Python", "APIs"),
        depends_on=("EC01",),
    ),
    T("EC04", "Cart API", "URGENT", required_skills=("Python", "APIs"), depends_on=("EC01",)),
    T(
        "EC05",
        "Product listing page",
        "HIGH",
        required_skills=("React",),
        depends_on=("EC02", "EC03"),
        acceptance_criteria="Products show name, price, stock and image.",
        evidence_policy=svc.EvidencePolicy.NOTE,
    ),
    T("EC06", "Checkout UI", "HIGH", required_skills=("React",), depends_on=("EC02", "EC04")),
    T(
        "EC07",
        "Payment gateway integration",
        "URGENT",
        required_skills=("Python", "APIs"),
        depends_on=("EC04",),
    ),
    T("EC08", "Search & filters", "MEDIUM", required_skills=("React",), depends_on=("EC03",)),
    T(
        "EC09",
        "Order confirmation emails",
        "LOW",
        required_skills=("Python",),
        depends_on=("EC01",),
    ),
    T("EC10", "Wishlist page", "MEDIUM", required_skills=("React",), depends_on=("EC02",)),
    T("EC11", "iOS build setup", "MEDIUM", required_skills=("iOS",)),
    T(
        "EC12",
        "End-to-end testing",
        "HIGH",
        required_skills=("Testing",),
        depends_on=("EC05", "EC06", "EC07"),
    ),
]


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
        if db.execute(select(Project.id).where(Project.name == NAME)).first():
            print("Demo project already exists; nothing to do.")
            return 0

        kavitha = _principal(db, "kavitha")
        for username, skills in SKILLS.items():
            user = db.execute(select(User).where(User.username == username)).scalar_one()
            svc.set_user_skills(db, kavitha, user.id, skills)
        if not db.execute(
            select(Skill.id).where(Skill.organization_id == org.id, Skill.name == "iOS")
        ).first():
            db.add(Skill(organization_id=org.id, name="iOS"))  # in the catalog, but nobody has it
        db.commit()

        web = db.execute(
            select(Team).where(Team.organization_id == org.id, Team.name == "Web Platform")
        ).scalar_one()
        project = svc.create_project(
            db,
            kavitha,
            team_id=web.id,
            name=NAME,
            description="Online store: catalog, cart, checkout and payments.",
        )
        report = svc.import_backlog(db, kavitha, project.id, BACKLOG)
        if not report.ok:
            print("Backlog invalid: " + "; ".join(report.errors), file=sys.stderr)
            return 1
        svc.approve_backlog(db, kavitha, project.id)
        result = svc.start_project(db, kavitha, project.id)
        db.commit()

    print(f"Created '{NAME}' with {len(BACKLOG)} tasks and started it.")
    for a in result.assigned:
        print(f"  assigned  {a['key']} {a['title']} -> {a['assignee_name']}  ({a['reason']})")
    for a in result.waiting_for_capacity:
        print(f"  waiting   {a['key']} {a['title']}  ({a['reason']})")
    for a in result.needs_decision:
        print(f"  DECISION  {a['key']} {a['title']}  ({a['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
