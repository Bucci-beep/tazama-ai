"""Tests for LangGraph SQLite timeline dependency injection."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from tazama.mcp.contracts import PatientObservations
from tazama.orchestration.graph import build_triage_graph
from tazama.patients.models import ObservationRecord, PatientTimeline


def record(obs_id: str, minute: int, kind: str) -> ObservationRecord:
    return ObservationRecord(
        observation_id=obs_id,
        case_id="CASE-001",
        recorded_at=datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
        + timedelta(minutes=minute),
        observation_type=kind,
        observations=PatientObservations(heart_rate_bpm=80.0),
    )


def initial_state(case_id: str) -> dict:
    return {"case_id": case_id, "status": "pending", "reason": None}


def test_graph_loads_baseline_and_recheck():
    timeline = PatientTimeline(case_id="CASE-001")
    timeline.add_record(record("OBS-001", 0, "baseline"))
    timeline.add_record(record("OBS-002", 10, "recheck"))

    repository = Mock()
    repository.get_timeline.return_value = timeline

    graph = build_triage_graph(repository)
    result = graph.invoke(initial_state("CASE-001"))

    repository.get_timeline.assert_called_once_with("CASE-001")
    assert result["observation_count"] == 2
    assert result["has_baseline"] is True
    assert result["has_rechecks"] is True
    assert result["latest_observation_id"] == "OBS-002"
    assert result["status"] == "awaiting_clinician_review"


def test_graph_handles_empty_patient_timeline():
    repository = Mock()
    repository.get_timeline.return_value = PatientTimeline(case_id="CASE-001")

    graph = build_triage_graph(repository)
    result = graph.invoke(initial_state("CASE-001"))

    assert result["observation_count"] == 0
    assert result["has_baseline"] is False
    assert result["has_rechecks"] is False
    assert result["latest_observation_id"] is None
    assert result["status"] == "awaiting_clinician_review"


def test_invalid_case_never_queries_database():
    repository = Mock()
    graph = build_triage_graph(repository)

    result = graph.invoke(initial_state("  "))

    repository.get_timeline.assert_not_called()
    assert result["status"] == "invalid_input"
    assert result["reason"] == "CASE_ID_MISSING"


def test_graph_without_repository_remains_compatible():
    graph = build_triage_graph()
    result = graph.invoke(initial_state("CASE-001"))

    assert result["status"] == "awaiting_clinician_review"
    assert "observation_count" not in result
