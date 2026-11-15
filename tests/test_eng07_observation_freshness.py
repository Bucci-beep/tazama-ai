"""ENG07-01: fail closed when observations change mid-workflow.

This tests the agreed freshness precondition.
All data and storage are synthetic and temporary.
"""

import asyncio
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

CASE_ID = "SYN-ENG07-FRESHNESS"
START = datetime(2026, 11, 12, 8, tzinfo=UTC)


def make_record(
    observation_id: str, offset_minutes: int, *, baseline: bool
) -> ObservationRecord:
    return ObservationRecord(
        observation_id=observation_id,
        case_id=CASE_ID,
        recorded_at=START + timedelta(minutes=offset_minutes),
        observation_type="baseline" if baseline else "recheck",
        observations=PatientObservations(
            adult_chart_applies="yes",  # Explicit synthetic nurse confirmation.
            heart_rate_bpm=80.0 + offset_minutes,
            respiratory_rate_bpm=16.0,
            systolic_bp_mmhg=120.0,
            temperature_c=36.8,
            consciousness="alert",
            mobility="walking",
            trauma=False,
        ),
    )


@pytest.mark.asyncio
async def test_new_observation_during_workflow_rejects_stale_review(
    tmp_path, monkeypatch
):
    """An obsolete workflow must not persist or confirm a current review."""
    database = Database(tmp_path / "eng07-freshness.sqlite3")
    database.initialize()
    observations = ObservationRepository(database)
    reviews = ReviewRepository(database)
    reviews.initialize()
    observations.save(make_record("OBS-A", 0, baseline=True))

    snapshot_reached = asyncio.Event()
    resume_history = asyncio.Event()
    seen_history = []
    seen_priority = []
    submitted = []

    async def history(request):
        seen_history.append(request)
        snapshot_reached.set()
        await resume_history.wait()
        return CompareHistoryResult(
            case_id=request.case_id, status="insufficient_history"
        )

    async def priority(request):
        seen_priority.append(request)
        return determine_priority(request.observations, request.signs)

    async def time_context():
        return TimeContext(
            timezone="UTC",
            datetime=START,
            day_of_week="Thursday",
            is_dst=False,
        )

    async def explanation(_evidence):
        return {}

    async def submit_locally(request, database_path, workflow_run_id=None):
        assert str(database_path) == str(database.database_path)
        submitted.append(request)
        return reviews.submit(request)

    monkeypatch.setattr(mcp_graph, "submit_review_via_mcp", submit_locally)
    graph = build_mcp_triage_graph(
        observations,
        history_tool=history,
        priority_tool=priority,
        explanation_tool=explanation,
        time_tool=time_context,
    )

    task = asyncio.create_task(
        graph.ainvoke(
            {"case_id": CASE_ID, "status": "pending", "reason": None, "signs": []}
        )
    )
    try:
        await asyncio.wait_for(snapshot_reached.wait(), timeout=5)
        observations.save(make_record("OBS-B", 10, baseline=False))
    finally:
        resume_history.set()

    result = await asyncio.wait_for(task, timeout=10)
    latest = observations.get_timeline(CASE_ID).latest()
    assert latest is not None
    assert latest.observation_id == "OBS-B"

    # ENG02 invariant: processing stays tied to the captured observation A.
    assert len(seen_history) == 1
    assert seen_history[0].after.obs_id == "OBS-A"
    assert len(seen_priority) == 1
    assert seen_priority[0].observations.heart_rate_bpm == 80.0
    assert result["latest_observation_id"] == "OBS-A"
    assert result["priority_status"] == "complete"

    # Stale submission must fail closed; do not turn it into a success claim.
    assert len(submitted) == 1
    assert submitted[0].observation_id == "OBS-A"
    assert reviews.get_by_observation_id("OBS-A") is None
    assert result["review_submission_status"] == "unconfirmed"
    assert result["review_request_id"] is None
    assert result["status"] == "review_submission_failed"
    with database.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM review_requests").fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM review_request_events").fetchone()[
                0
            ]
            == 0
        )

    print(
        "ENG07-01 safe rejection: "
        f"snapshot={result['latest_observation_id']}, "
        f"database_latest={latest.observation_id}, "
        f"submission_status={result['review_submission_status']}"
    )


@pytest.mark.asyncio
async def test_fresh_reassessment_of_latest_observation_still_persists(
    tmp_path, monkeypatch
):
    """A new workflow for B succeeds; ordinary idempotency remains intact."""
    database = Database(tmp_path / "eng07-latest.sqlite3")
    database.initialize()
    observations = ObservationRepository(database)
    reviews = ReviewRepository(database)
    reviews.initialize()
    observations.save(make_record("OBS-A", 0, baseline=True))
    observations.save(make_record("OBS-B", 10, baseline=False))

    async def history(request):
        return CompareHistoryResult(case_id=request.case_id, status="differences_found")

    async def priority(request):
        return determine_priority(request.observations, request.signs)

    async def time_context():
        return TimeContext(
            timezone="UTC", datetime=START, day_of_week="Thursday", is_dst=False
        )

    async def explanation(_evidence):
        return {}

    async def submit_locally(request, database_path, workflow_run_id=None):
        return reviews.submit(request)

    monkeypatch.setattr(mcp_graph, "submit_review_via_mcp", submit_locally)
    graph = build_mcp_triage_graph(
        observations,
        history_tool=history,
        priority_tool=priority,
        explanation_tool=explanation,
        time_tool=time_context,
    )
    state = {"case_id": CASE_ID, "status": "pending", "reason": None, "signs": []}
    first = await graph.ainvoke(state)
    second = await graph.ainvoke(state)
    assert first["latest_observation_id"] == "OBS-B"
    assert first["review_submission_status"] == "persisted"
    assert first["review_request_id"]
    assert second["review_submission_status"] == "persisted"
    assert second["review_request_id"] == first["review_request_id"]
    assert (
        reviews.get_by_observation_id("OBS-B").request_id == first["review_request_id"]
    )
    with database.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM review_requests").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM review_request_events").fetchone()[
                0
            ]
            == 1
        )


def test_preexisting_historical_review_remains_immutable_after_new_observation(
    tmp_path,
):
    """Freshness rejection does not erase a review that was valid when created."""
    from tazama.storage.reviews import SubmitReviewRequest

    database = Database(tmp_path / "eng07-historical.sqlite3")
    database.initialize()
    observations = ObservationRepository(database)
    reviews = ReviewRepository(database)
    reviews.initialize()
    observations.save(make_record("OBS-A", 0, baseline=True))
    request = SubmitReviewRequest(
        case_id=CASE_ID,
        actor_id="SYSTEM-AGENT",
        observation_id="OBS-A",
        comparison_status="insufficient_history",
        evidence={"synthetic": True},
    )
    existing = reviews.submit(request)
    observations.save(make_record("OBS-B", 10, baseline=False))
    with pytest.raises(ValueError, match="OBSERVATION_SUPERSEDED"):
        reviews.submit(request)
    saved = reviews.get_by_observation_id("OBS-A")
    assert saved is not None
    assert saved.request_id == existing.request_id
    assert saved.revision == 1
    with database.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM review_requests").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM review_request_events").fetchone()[
                0
            ]
            == 1
        )
