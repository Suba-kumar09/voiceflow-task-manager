"""HTTP hardening: security headers and size-capped request bodies (Phase 10)."""

from fastapi import Request
from starlette.responses import Response

# The API only returns JSON: nothing may be framed, sniffed or run as a page.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def apply_security_headers(request: Request, response: Response, *, production: bool) -> None:
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), geolocation=(), payment=()")
    if not request.url.path.startswith("/api/docs"):  # Swagger UI needs its own scripts
        h.setdefault("Content-Security-Policy", _API_CSP)
    if request.url.path.startswith("/api/v1/") and "Cache-Control" not in h:
        h["Cache-Control"] = "no-store"  # personal task data must not sit in shared caches
    if production:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


async def read_body_limited(request: Request, max_bytes: int) -> bytes:
    """Read the body but stop as soon as it exceeds max_bytes (no unbounded memory use)."""
    from app.voice.audio import AudioTooLargeError  # the only caller is the audio endpoint

    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise AudioTooLargeError("The recording is too long. Please say it in a shorter sentence.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise AudioTooLargeError(
                "The recording is too long. Please say it in a shorter sentence."
            )
        chunks.append(chunk)
    return b"".join(chunks)
