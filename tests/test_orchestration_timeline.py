"""Tests for the SQLite-to-orchestration boundary."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from tazama.mcp.contracts import PatientObservations
from tazama.orchestration.timeline import load_timeline
from tazama.patients.models import ObservationRecord, PatientTimeline


def make_record(obs_id: str, minute: int, kind: str) -> ObservationRecord:
    return ObservationRecord(
        observation_id=obs_id,
        case_id="CASE-001",
        recorded_at=datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
        + timedelta(minutes=minute),
        observation_type=kind,
        observations=PatientObservations(heart_rate_bpm=80.0),
    )


def test_empty_timeline():
    repo = Mock()
    repo.get_timeline.return_value = PatientTimeline(case_id="CASE-001")

    result = load_timeline("CASE-001", repo)

    assert result["observation_count"] == 0
    assert result["has_baseline"] is False
    assert result["has_rechecks"] is False
    assert result["latest_observation_id"] is None
    repo.get_timeline.assert_called_once_with("CASE-001")


def test_baseline_only():
    timeline = PatientTimeline(case_id="CASE-001")
    timeline.add_record(make_record("OBS-001", 0, "baseline"))

    repo = Mock()
    repo.get_timeline.return_value = timeline

    result = load_timeline("CASE-001", repo)

    assert result["observation_count"] == 1
    assert result["has_baseline"] is True
    assert result["has_rechecks"] is False
    assert result["latest_observation_id"] == "OBS-001"


def test_baseline_and_recheck():
    timeline = PatientTimeline(case_id="CASE-001")
    timeline.add_record(make_record("OBS-001", 0, "baseline"))
    timeline.add_record(make_record("OBS-002", 10, "recheck"))

    repo = Mock()
    repo.get_timeline.return_value = timeline

    result = load_timeline("CASE-001", repo)

    assert result["observation_count"] == 2
    assert result["has_baseline"] is True
    assert result["has_rechecks"] is True
    assert result["latest_observation_id"] == "OBS-002"
