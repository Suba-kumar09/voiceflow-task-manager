"""Idempotency for retry-sensitive mutations (CLAUDE.md sections 8.2, 10).

The first request with a given (actor, Idempotency-Key) runs and its response is stored in the
same transaction as the change. A retry with the same key and the same body gets the stored
response; nothing runs twice. Reusing a key for a different request is refused.
"""

import hashlib
import json
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import IdempotencyRecord
from app.services.errors import ConflictError, RuleViolationError

MAX_KEY_LENGTH = 100


def _hash(endpoint: str, payload: dict) -> str:
    raw = json.dumps({"endpoint": endpoint, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _replay(record: IdempotencyRecord, request_hash: str) -> tuple[int, dict]:
    if record.request_hash != request_hash:
        raise RuleViolationError(
            "This Idempotency-Key was already used for a different request.",
            code="idempotency_key_reused",
        )
    return record.response_status, record.response_body


def run_idempotent(
    db: Session,
    *,
    actor_user_id: uuid.UUID,
    key: str,
    endpoint: str,
    payload: dict,
    action: Callable[[], tuple[int, dict]],
) -> tuple[int, dict, bool]:
    """Run `action` once per key. Returns (status, body, replayed). Commits on success."""
    key = key.strip()
    if not key or len(key) > MAX_KEY_LENGTH:
        raise RuleViolationError(f"Idempotency-Key must be 1-{MAX_KEY_LENGTH} characters.")
    request_hash = _hash(endpoint, payload)

    def find() -> IdempotencyRecord | None:
        return db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.actor_user_id == actor_user_id, IdempotencyRecord.key == key
            )
        ).scalar_one_or_none()

    existing = find()
    if existing is not None:
        return (*_replay(existing, request_hash), True)

    status, body = action()
    db.add(
        IdempotencyRecord(
            actor_user_id=actor_user_id,
            key=key,
            endpoint=endpoint,
            request_hash=request_hash,
            response_status=status,
            response_body=body,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        # A concurrent request with the same key committed first: return its stored result.
        db.rollback()
        winner = find()
        if winner is None:
            raise ConflictError("Concurrent request conflict. Please retry.") from exc
        return (*_replay(winner, request_hash), True)
    return status, body, False
