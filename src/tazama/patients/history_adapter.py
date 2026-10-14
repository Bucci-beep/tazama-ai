"""Adapt persisted patient observations to the clinical history MCP contract.

This module performs data translation only.
It does not calculate clinical scores or determine deterioration.
"""

from tazama.clinical.history import (
    CompareHistoryRequest,
    CompareHistoryResult,
    TimedObservation,
    compare_with_history,
)
from tazama.patients.models import ObservationRecord, PatientTimeline


def to_timed_observation(record: ObservationRecord) -> TimedObservation:
    """Preserve observation identity, UTC timestamp and recorded values."""
    return TimedObservation(
        obs_id=record.observation_id,
        taken_utc=record.recorded_at.isoformat(),
        observations=record.observations,
    )


def to_history_request(timeline: PatientTimeline) -> CompareHistoryRequest:
    """Prepare a comparison of the two most recent observations.

    The existing history comparator handles missing prior observations.
    """
    if not timeline.records:
        raise ValueError("Cannot compare an empty patient timeline")

    after = timeline.records[-1]
    before = timeline.records[-2] if len(timeline.records) >= 2 else None

    return CompareHistoryRequest(
        case_id=timeline.case_id,
        before=to_timed_observation(before) if before is not None else None,
        after=to_timed_observation(after),
    )


def compare_timeline(timeline: PatientTimeline) -> CompareHistoryResult:
    """Run the existing deterministic comparator on the latest two records."""
    return compare_with_history(to_history_request(timeline))
