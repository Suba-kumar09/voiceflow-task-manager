"""Consistent error responses. Internal details never reach the client."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: list[dict] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def _respond(status: int, code: str, message: str, details: list[dict] | None = None):
    body = ErrorResponse(
        error=ErrorBody(
            code=code, message=message, request_id=request_id_var.get(), details=details
        )
    )
    return JSONResponse(status_code=status, content=body.model_dump(exclude_none=True))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            429: "too_many_requests",
        }.get(exc.status_code, "http_error")
        return _respond(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return _respond(422, "validation_error", "Request validation failed.", details)

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception):
        logger.exception("Unhandled error")
        return _respond(500, "internal_error", "An unexpected error occurred.")
