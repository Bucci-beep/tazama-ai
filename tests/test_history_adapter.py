"""Integration tests for the persistence-to-history contract adapter."""

from datetime import UTC, datetime, timedelta

import pytest

from tazama.mcp.contracts import PatientObservations
from tazama.patients.history_adapter import (
    compare_timeline,
    to_history_request,
    to_timed_observation,
)
from tazama.patients.models import ObservationRecord, PatientTimeline


def make_record(
    observation_id: str,
    minutes: int,
    observation_type: str,
    heart_rate: float,
) -> ObservationRecord:
    return ObservationRecord(
        observation_id=observation_id,
        case_id="CASE-ADAPTER-001",
        recorded_at=datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
        + timedelta(minutes=minutes),
        observation_type=observation_type,
        observations=PatientObservations(
            heart_rate_bpm=heart_rate,
            mobility="walking",
            trauma=False,
        ),
    )


def test_adapter_preserves_identity_timestamp_and_observations():
    record = make_record("OBS-001", 0, "baseline", 80.0)

    converted = to_timed_observation(record)

    assert converted.obs_id == record.observation_id
    assert converted.taken_utc == record.recorded_at.isoformat()
    assert converted.observations == record.observations
    assert converted.observations.mobility == "walking"
    assert converted.observations.trauma is False


def test_adapter_builds_request_from_latest_two_records():
    timeline = PatientTimeline(case_id="CASE-ADAPTER-001")

    timeline.add_record(make_record("OBS-001", 0, "baseline", 80.0))
    timeline.add_record(make_record("OBS-002", 10, "recheck", 85.0))
    timeline.add_record(make_record("OBS-003", 20, "recheck", 95.0))

    request = to_history_request(timeline)

    assert request.case_id == timeline.case_id
    assert request.before.obs_id == "OBS-002"
    assert request.after.obs_id == "OBS-003"


def test_adapter_reports_numeric_differences_without_clinical_interpretation():
    timeline = PatientTimeline(case_id="CASE-ADAPTER-001")

    timeline.add_record(make_record("OBS-001", 0, "baseline", 80.0))
    timeline.add_record(make_record("OBS-002", 10, "recheck", 95.0))

    result = compare_timeline(timeline)

    assert result.status == "differences_found"
    assert len(result.changes) == 1

    change = result.changes[0]

    assert change.field == "heart_rate_bpm"
    assert change.before == 80.0
    assert change.after == 95.0
    assert change.before_obs_id == "OBS-001"
    assert change.after_obs_id == "OBS-002"


def test_adapter_preserves_insufficient_history_status():
    timeline = PatientTimeline(case_id="CASE-ADAPTER-001")
    timeline.add_record(make_record("OBS-001", 0, "baseline", 80.0))

    result = compare_timeline(timeline)

    assert result.status == "insufficient_history"
    assert result.reason == "NO_BASELINE"


def test_adapter_refuses_empty_timeline():
    timeline = PatientTimeline(case_id="CASE-ADAPTER-001")

    with pytest.raises(ValueError, match="empty patient timeline"):
        to_history_request(timeline)
