"""Domain models for reassessment obligations."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecheckObligation(BaseModel):
    """A scheduled reassessment task, not a clinical decision."""

    model_config = ConfigDict(extra="forbid", strict=True)

    obligation_id: str = Field(default_factory=lambda: str(uuid4()))
    case_id: str = Field(min_length=1)
    due_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: Literal["scheduled", "completed", "cancelled"] = "scheduled"
    policy_reference: str = Field(min_length=1)

    @field_validator("due_at", "created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")
        return value.astimezone(UTC)
