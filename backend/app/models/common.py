"""Shared column helpers."""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def str_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Store an enum as VARCHAR + CHECK constraint (easier to migrate than a PG enum type)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
