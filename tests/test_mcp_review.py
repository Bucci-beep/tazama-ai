"""Real MCP transport tests for clinician review submission."""

from datetime import UTC, datetime

import pytest

from tazama.mcp.contracts import PatientObservations
from tazama.orchestration.mcp_review import (
    attest_review_via_mcp,
    submit_review_via_mcp,
)
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import (
    ReviewRepository,
    SubmitAttestation,
    SubmitReviewRequest,
)


@pytest.fixture
def prepared_database(tmp_path):
    path = tmp_path / "tazama.sqlite3"
    database = Database(path)
    database.initialize()

    ObservationRepository(database).save(
        ObservationRecord(
            observation_id="OBS-MCP-1",
            case_id="CASE-MCP-1",
            observation_type="baseline",
            recorded_at=datetime(2026, 10, 14, tzinfo=UTC),
            observations=PatientObservations(heart_rate_bpm=80.0),
        )
    )

    return path, database


def review_request(**overrides):
    values = {
        "case_id": "CASE-MCP-1",
        "actor_id": "SYSTEM-AGENT",
        "observation_id": "OBS-MCP-1",
        "comparison_status": "insufficient_history",
        "evidence": {"reason": "Baseline only"},
    }
    values.update(overrides)
    return SubmitReviewRequest(**values)


@pytest.mark.asyncio
async def test_mcp_submission_persists_review_and_audit(prepared_database):
    path, database = prepared_database

    result = await submit_review_via_mcp(review_request(), path)

    assert result.status == "pending"

    reviews = ReviewRepository(database).get_pending()
    assert len(reviews) == 1
    assert reviews[0].request_id == result.request_id

    with database.connect() as connection:
        events = connection.execute(
            "SELECT action FROM review_request_events"
        ).fetchall()

    assert events == [("review.requested",)]


@pytest.mark.asyncio
async def test_mcp_retry_returns_existing_request(prepared_database):
    path, database = prepared_database

    first = await submit_review_via_mcp(review_request(), path)
    second = await submit_review_via_mcp(review_request(), path)

    assert first.request_id == second.request_id
    assert len(ReviewRepository(database).get_pending()) == 1

    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM review_request_events"
        ).fetchone()[0]

    assert count == 1


@pytest.mark.asyncio
async def test_mcp_records_idempotent_demo_attestation(prepared_database):
    path, database = prepared_database
    review = await submit_review_via_mcp(review_request(), path)
    command = SubmitAttestation(
        request_id=review.request_id,
        clinician_id="DEMO-CLINICIAN-1",
        action="approved",
    )

    first = await attest_review_via_mcp(command, path)
    second = await attest_review_via_mcp(command, path)

    assert first.event_id == second.event_id
    assert first.identity_assurance == "asserted_demo_identity"
    assert ReviewRepository(database).get_pending()[0].request_id == review.request_id


@pytest.mark.asyncio
async def test_mcp_conflicting_evidence_fails_closed(prepared_database):
    path, database = prepared_database

    await submit_review_via_mcp(review_request(), path)

    with pytest.raises(RuntimeError, match="MCP_REVIEW_SUBMISSION_FAILED"):
        await submit_review_via_mcp(
            review_request(evidence={"reason": "Changed evidence"}),
            path,
        )

    assert len(ReviewRepository(database).get_pending()) == 1


@pytest.mark.asyncio
async def test_mcp_rejects_cross_case_observation(prepared_database):
    path, database = prepared_database

    with pytest.raises(RuntimeError, match="MCP_REVIEW_SUBMISSION_FAILED"):
        await submit_review_via_mcp(
            review_request(case_id="CASE-OTHER"),
            path,
        )

    assert ReviewRepository(database).get_pending() == []


@pytest.mark.asyncio
async def test_missing_database_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        await submit_review_via_mcp(
            review_request(),
            tmp_path / "missing.sqlite3",
        )
