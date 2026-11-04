"""ENG03 acceptance: revision lineage and fail-closed MCP submissions."""

from datetime import UTC, datetime, timedelta

import pytest

from tazama.mcp.contracts import PatientObservations
from tazama.orchestration import mcp_graph
from tazama.orchestration.mcp_graph import build_mcp_triage_graph
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRepository, SubmitReviewRequest

CASE_ID = "CASE-ENG03-MCP"
OBSERVATION_ID = "OBS-ENG03-2"


def setup_case(tmp_path):
    database = Database(tmp_path / "eng03-mcp.sqlite3")
    database.initialize()
    observations = ObservationRepository(database)
    for index in range(2):
        observations.save(
            ObservationRecord(
                observation_id=f"OBS-ENG03-{index + 1}",
                case_id=CASE_ID,
                recorded_at=datetime(2026, 10, 14, 8, tzinfo=UTC)
                + timedelta(minutes=10 * index),
                observation_type="baseline" if index == 0 else "recheck",
                observations=PatientObservations(
                    heart_rate_bpm=float(80 + index * 10),
                    respiratory_rate_bpm=12.0,
                    systolic_bp_mmhg=120.0,
                    temperature_c=37.0,
                    consciousness="alert",
                    mobility="walking",
                    trauma=False,
                ),
            )
        )
    reviews = ReviewRepository(database)
    reviews.initialize()
    return observations, reviews


def seed_first_revision(reviews):
    return reviews.submit(
        SubmitReviewRequest(
            case_id=CASE_ID,
            actor_id="SYSTEM-AGENT",
            observation_id=OBSERVATION_ID,
            comparison_status="insufficient_history",
            evidence={"seeded_prior_revision": True},
        )
    )


def state():
    return {"case_id": CASE_ID, "status": "pending", "reason": None}


def all_revisions(reviews):
    with reviews.database.connect() as connection:
        return connection.execute(
            "SELECT request_id, revision, supersedes_request_id, evidence_json "
            "FROM review_requests WHERE observation_id = ? ORDER BY revision",
            (OBSERVATION_ID,),
        ).fetchall()


@pytest.mark.asyncio
async def test_mcp_changed_evidence_creates_immutable_successor(tmp_path, monkeypatch):
    observations, reviews = setup_case(tmp_path)
    predecessor = seed_first_revision(reviews)
    received = []

    async def submit(request, database_path, workflow_run_id=None):
        received.append(request)
        return reviews.submit(request)

    monkeypatch.setattr(mcp_graph, "submit_review_via_mcp", submit)
    result = await build_mcp_triage_graph(observations).ainvoke(state())

    assert result["review_submission_status"] == "persisted"
    assert received[0].expected_current_request_id == predecessor.request_id
    successor = reviews.get_by_observation_id(OBSERVATION_ID)
    assert successor is not None
    assert successor.revision == 2
    assert successor.supersedes_request_id == predecessor.request_id
    assert result["review_request_id"] == successor.request_id
    rows = all_revisions(reviews)
    assert len(rows) == 2
    assert rows[0][0] == predecessor.request_id
    assert rows[0][1] == 1
    assert rows[0][2] is None
    assert rows[1][0] == successor.request_id
    assert rows[1][1] == 2
    assert rows[1][2] == predecessor.request_id


@pytest.mark.asyncio
async def test_mcp_stale_precondition_fails_closed(tmp_path, monkeypatch):
    observations, reviews = setup_case(tmp_path)
    predecessor = seed_first_revision(reviews)
    captured = []

    async def concurrent_submit(request, database_path, workflow_run_id=None):
        captured.append(request)
        # Another workflow wins the race after this graph captured revision 1.
        reviews.submit(
            request.model_copy(update={"evidence": {"competing_workflow": True}})
        )
        # Original stale request must be rejected by optimistic concurrency.
        return reviews.submit(request)

    monkeypatch.setattr(mcp_graph, "submit_review_via_mcp", concurrent_submit)
    result = await build_mcp_triage_graph(observations).ainvoke(state())

    assert captured[0].expected_current_request_id == predecessor.request_id
    assert result["review_submission_status"] == "unconfirmed"
    assert result["review_request_id"] is None
    assert result["status"] == "review_submission_failed"
    rows = all_revisions(reviews)
    assert len(rows) == 2
    assert rows[1][2] == predecessor.request_id
    assert reviews.get_by_observation_id(OBSERVATION_ID).evidence == {
        "competing_workflow": True
    }


@pytest.mark.asyncio
async def test_mcp_successor_timeout_is_not_reconciled(tmp_path, monkeypatch):
    observations, reviews = setup_case(tmp_path)
    predecessor = seed_first_revision(reviews)
    captured = []

    async def persist_then_timeout(request, database_path, workflow_run_id=None):
        captured.append(request)
        reviews.submit(request)
        raise TimeoutError("Simulated response loss after successor persistence")

    monkeypatch.setattr(mcp_graph, "submit_review_via_mcp", persist_then_timeout)
    result = await build_mcp_triage_graph(observations).ainvoke(state())

    assert captured[0].expected_current_request_id == predecessor.request_id
    assert result["review_submission_status"] == "unconfirmed"
    assert result["review_request_id"] is None
    assert result["status"] == "review_submission_failed"
    successor = reviews.get_by_observation_id(OBSERVATION_ID)
    assert successor is not None
    assert successor.revision == 2
    assert successor.supersedes_request_id == predecessor.request_id
    assert len(all_revisions(reviews)) == 2
