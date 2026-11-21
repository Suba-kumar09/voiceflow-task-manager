"""FastAPI application factory."""

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.auth.throttle import LoginThrottle
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, request_id_var
from app.core.security import apply_security_headers


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        # The interactive API docs are for development only.
        docs_url="/api/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
    )
    production = settings.environment == "production"

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        # Accept a client correlation ID only if it is a valid UUID; otherwise make one.
        incoming = request.headers.get("X-Request-ID", "")
        try:
            rid = str(uuid.UUID(incoming))
        except ValueError:
            rid = str(uuid.uuid4())
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        apply_security_headers(request, response, production=production)
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID", "X-CSRF-Token", "Idempotency-Key"],
    )

    app.state.login_throttle = LoginThrottle(
        max_failures=settings.login_max_failures,
        window_seconds=settings.login_failure_window_minutes * 60,
    )

    app.state.voice_limiter = LoginThrottle(
        max_failures=settings.voice_turns_per_minute, window_seconds=60
    )

    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
