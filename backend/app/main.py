"""FastAPI application factory."""

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, request_id_var


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

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
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID", "X-CSRF-Token", "Idempotency-Key"],
    )

    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
