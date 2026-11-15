"""ENG07-02A: test-only investigation of timeout reconciliation freshness.

A review can be correctly persisted for snapshot A and its MCP response lost.
If observation B arrives before reconciliation, the workflow must not report
A as a confirmed *current* review. No clinical thresholds are introduced.
"""

from datetime import UTC, datetime, timedelta

import pytest

from tazama.clinical.history import CompareHistoryResult
from tazama.clinical.priority import determine_priority
from tazama.mcp.contracts import PatientObservations
from tazama.orchestration import mcp_graph
from tazama.orchestration.mcp_graph import build_mcp_triage_graph
from tazama.orchestration.mcp_time import TimeContext
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRepository

CASE_ID = "SYN-ENG07-RECONCILIATION"
START = datetime(2026, 11, 12, 8, tzinfo=UTC)


def observation(observation_id: str, minutes: int, kind: str) -> ObservationRecord:
    return ObservationRecord(
        observation_id=observation_id,
        case_id=CASE_ID,
        observation_type=kind,
        recorded_at=START + timedelta(minutes=minutes),
        observations=PatientObservations(
            adult_chart_applies="yes",
            heart_rate_bpm=80.0 if observation_id == "OBS-A" else 90.0,
            respiratory_rate_bpm=16.0,
            systolic_bp_mmhg=120.0,
            temperature_c=36.8,
            consciousness="alert",
            mobility="walking",
            trauma=False,
        ),
    )


async def history(request):
    return CompareHistoryResult(case_id=request.case_id, status="insufficient_history")


async def priority(request):
    return determine_priority(request.observations, request.signs)


async def time_context():
    return TimeContext(
        timezone="UTC", datetime=START, day_of_week="Thursday", is_dst=False
    )


async def explanation(_evidence):
    return {}


@pytest.mark.asyncio
async def test_timeout_reconciliation_does_not_confirm_superseded_snapshot(
    tmp_path, monkeypatch
):
    """Desired policy: a reconciled A review cannot be presented as current after B."""
    database = Database(tmp_path / "eng07-reconciliation.sqlite3")
    database.initialize()
    observations = ObservationRepository(database)
    observations.save(observation("OBS-A", 0, "baseline"))
    reviews = ReviewRepository(database)
    reviews.initialize()

    submitted = []

    async def persist_advance_then_timeout(request, database_path, *, workflow_run_id):
        # Mimics a successful MCP write whose response is lost in transit.
        assert str(database_path) == str(database.database_path)
        assert request.observation_id == "OBS-A"
        persisted = reviews.submit(request)
        submitted.append(persisted)
        # This occurs AFTER the valid write but BEFORE timeout reconciliation.
        observations.save(observation("OBS-B", 10, "recheck"))
        raise TimeoutError("Synthetic MCP response lost after persistence")

    monkeypatch.setattr(
        mcp_graph, "submit_review_via_mcp", persist_advance_then_timeout
    )
    graph = build_mcp_triage_graph(
        observations,
        history_tool=history,
        priority_tool=priority,
        explanation_tool=explanation,
        time_tool=time_context,
    )
    result = await graph.ainvoke(
        {"case_id": CASE_ID, "status": "pending", "reason": None, "signs": []}
    )

    assert len(submitted) == 1
    saved = reviews.get_by_observation_id("OBS-A")
    assert saved is not None
    assert saved.request_id == submitted[0].request_id
    assert saved.status == "pending"  # Legitimate immutable historical evidence.
    assert reviews.get_by_observation_id("OBS-B") is None
    assert observations.get_timeline(CASE_ID).latest().observation_id == "OBS-B"
    assert result["latest_observation_id"] == "OBS-A"  # ENG02 snapshot retained.
    assert result["priority_result"]["priority"] == "routine"

    # RED-phase acceptance criterion: reconciliation cannot confirm A as current.
    assert result["review_submission_status"] != "persisted", (
        "Timeout reconciliation confirmed OBS-A even though OBS-B was already latest"
    )
    assert result["review_request_id"] is None
    assert result["status"] == "review_submission_failed"
