"""Sign in / sign out."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_login_throttle
from app.api.v1.people import build_me
from app.auth.passwords import burn_verification_time, hash_password, needs_rehash, verify_password
from app.auth.principal import MutatingPrincipal
from app.auth.sessions import create_session, revoke_session
from app.auth.throttle import LoginThrottle
from app.core.config import get_settings
from app.db.session import get_db
from app.models import AuditOutcome, User
from app.models.common import utcnow
from app.schemas.identity import LoginIn, MeOut
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = "Invalid username or password."


@router.post("/login", response_model=MeOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    throttle: Annotated[LoginThrottle, Depends(get_login_throttle)],
) -> MeOut:
    settings = get_settings()
    username = body.username.strip().lower()
    client_ip = request.client.host if request.client else "unknown"
    keys = (f"user:{username}", f"ip:{client_ip}")

    if throttle.is_blocked(*keys):
        record_audit(
            db,
            action="auth.login",
            outcome=AuditOutcome.DENIED,
            details={"reason": "throttled", "username": username},
        )
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed sign-in attempts. Please wait and try again.",
        )

    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        burn_verification_time(body.password)
        ok = False
    else:
        ok = verify_password(user.password_hash, body.password) and user.is_active

    if not ok or user is None:
        throttle.record_failure(*keys)
        record_audit(
            db,
            action="auth.login",
            outcome=AuditOutcome.FAILURE,
            organization_id=user.organization_id if user else None,
            actor_user_id=user.id if user else None,
            details={"username": username},
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_CREDENTIALS)

    throttle.reset(f"user:{username}")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = utcnow()
    new = create_session(db, user, settings, client_ip, request.headers.get("user-agent"))
    record_audit(
        db,
        action="auth.login",
        outcome=AuditOutcome.SUCCESS,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
    )
    db.commit()

    response.set_cookie(
        settings.session_cookie_name,
        new.token,
        max_age=settings.session_absolute_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api",
    )
    return build_me(db, user, new.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    principal: MutatingPrincipal,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    settings = get_settings()
    revoke_session(db, principal.session_id)
    record_audit(
        db,
        action="auth.logout",
        outcome=AuditOutcome.SUCCESS,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        target_type="session",
        target_id=principal.session_id,
    )
    db.commit()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/api",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
