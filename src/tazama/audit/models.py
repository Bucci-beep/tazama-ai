"""Validated audit event models."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

AuditAction = Literal[
    "recheck.scheduled",
    "recheck.completed",
    "recheck.cancelled",
]


class AuditEvent(BaseModel):
    """An immutable-in-storage record of a reassessment action."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    case_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    action: AuditAction
    entity_id: str = Field(min_length=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, str] = Field(default_factory=dict)

    @field_validator("case_id", "actor_id", "entity_id")
    @classmethod
    def reject_blank_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Identifier cannot be blank")
        return value

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Audit timestamp must include a timezone")
        return value.astimezone(UTC)
