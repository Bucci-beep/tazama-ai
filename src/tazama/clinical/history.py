from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tazama.mcp.contracts import PatientObservations

NUMERIC_FIELDS = (
    "heart_rate_bpm",
    "respiratory_rate_bpm",
    "systolic_bp_mmhg",
    "temperature_c",
    "spo2_percent",
)


class TimedObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    obs_id: str = Field(min_length=1)
    taken_utc: str | None = None  # ISO 8601 with timezone, e.g. 2026-10-13T08:10:00+00:00
    observations: PatientObservations


class CompareHistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    before: TimedObservation | None = None
    after: TimedObservation


class ObservationChange(BaseModel):
    field: str
    before: float
    after: float
    before_obs_id: str
    after_obs_id: str


class CompareHistoryResult(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    status: Literal[
        "differences_found",
        "no_differences",
        "insufficient_history",
        "untrusted_reading",
    ]
    changes: list[ObservationChange] = Field(default_factory=list)
    not_comparable: list[str] = Field(default_factory=list)
    reason: str | None = None


def _parse(ts: str | None) -> datetime | None:
    """Return a timezone-aware datetime, or None if missing/invalid/naive."""
    if ts is None:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def compare_with_history(request: CompareHistoryRequest) -> CompareHistoryResult:
    """
    Report differences between a patient's earlier and new readings.

    This does NOT decide whether a difference is clinically significant.
    That is the job of the verified SATS scoring engine. A reading whose
    timestamp cannot be trusted is refused, never treated as reassuring.
    """

    def result(status, reason=None, changes=None, not_comparable=None):
        return CompareHistoryResult(
            case_id=request.case_id,
            status=status,
            reason=reason,
            changes=changes or [],
            not_comparable=not_comparable or [],
        )

    after_time = _parse(request.after.taken_utc)
    if after_time is None:
        return result("untrusted_reading", "NEW_READING_TIMESTAMP_MISSING_OR_INVALID")

    if request.before is None:
        return result("insufficient_history", "NO_BASELINE")

    before_time = _parse(request.before.taken_utc)
    if before_time is None:
        return result("insufficient_history", "BASELINE_TIMESTAMP_MISSING_OR_INVALID")

    if after_time <= before_time:
        return result("untrusted_reading", "NEW_READING_NOT_AFTER_BASELINE")

    changes: list[ObservationChange] = []
    not_comparable: list[str] = []
    for name in NUMERIC_FIELDS:
        b = getattr(request.before.observations, name)
        a = getattr(request.after.observations, name)
        if b is None or a is None:
            if (b is None) != (a is None):  # present on one side only
                not_comparable.append(name)
            continue
        if b != a:
            changes.append(
                ObservationChange(
                    field=name,
                    before=b,
                    after=a,
                    before_obs_id=request.before.obs_id,
                    after_obs_id=request.after.obs_id,
                )
            )

    status = "differences_found" if changes else "no_differences"
    return result(status, changes=changes, not_comparable=not_comparable)