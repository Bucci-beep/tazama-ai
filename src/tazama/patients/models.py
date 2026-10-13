from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tazama.mcp.contracts import PatientObservations


class ObservationRecord(BaseModel):
    """One synthetic observation event."""

    model_config = ConfigDict(extra="forbid", strict=True)

    observation_id: str = Field(default_factory=lambda: str(uuid4()))
    case_id: str = Field(min_length=1)
    recorded_at: datetime
    observation_type: Literal["baseline", "recheck"]
    observations: PatientObservations

    @field_validator("recorded_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must include a timezone")
        return value.astimezone(UTC)


class PatientTimeline(BaseModel):
    """Chronological observation history for one case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    records: list[ObservationRecord] = Field(default_factory=list)

    def add_record(self, record: ObservationRecord) -> None:
        if record.case_id != self.case_id:
            raise ValueError("Observation belongs to another case")

        if any(
            existing.observation_id == record.observation_id
            for existing in self.records
        ):
            raise ValueError("Duplicate observation ID")

        if not self.records and record.observation_type != "baseline":
            raise ValueError("First observation must be baseline")

        if self.records and record.observation_type == "baseline":
            raise ValueError("Baseline already exists")

        if self.records and record.recorded_at <= self.records[-1].recorded_at:
            raise ValueError("Observation timestamp must increase")

        self.records.append(record)

    def latest(self) -> ObservationRecord | None:
        return self.records[-1] if self.records else None

    def baseline(self) -> ObservationRecord | None:
        return self.records[0] if self.records else None
