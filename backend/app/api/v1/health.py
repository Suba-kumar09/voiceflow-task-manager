"""Public health/readiness endpoints (the only unauthenticated routes, per CLAUDE.md)."""

import logging
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.db.migrations import head_revision
from app.db.session import DatabaseNotConfiguredError, current_migration_revision, get_engine

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


class HealthOut(BaseModel):
    status: Literal["ok"]


class ReadinessOut(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable", "not_configured"]
    migrations: Literal["up_to_date", "pending", "unknown"]


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Liveness: the process is up. Does not touch the database."""
    return HealthOut(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessOut,
    responses={503: {"model": ReadinessOut}},
)
def ready(response: Response) -> ReadinessOut:
    """Readiness: database reachable and migrated to the latest revision."""
    try:
        current = current_migration_revision(get_engine())
    except DatabaseNotConfiguredError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessOut(status="not_ready", database="not_configured", migrations="unknown")
    except Exception:
        logger.warning("Readiness check: database unavailable", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessOut(status="not_ready", database="unavailable", migrations="unknown")

    if current != head_revision():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessOut(status="not_ready", database="ok", migrations="pending")
    return ReadinessOut(status="ready", database="ok", migrations="up_to_date")
