"""Tests for atomic review-request persistence."""

import sqlite3
from datetime import UTC, datetime

import pytest

from tazama.mcp.contracts import PatientObservations
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRepository, SubmitReviewRequest


@pytest.fixture
def setup(tmp_path):
    database = Database(tmp_path / "reviews.sqlite3")
    database.initialize()
    reviews = ReviewRepository(database)
    reviews.initialize()

    ObservationRepository(database).save(
        ObservationRecord(
            observation_id="OBS-1",
            case_id="CASE-1",
            recorded_at=datetime(2026, 10, 14, tzinfo=UTC),
            observation_type="baseline",
            observations=PatientObservations(heart_rate_bpm=80.0),
        )
    )
    return database, reviews


def request(**overrides):
    values = {
        "case_id": "CASE-1",
        "actor_id": "SYSTEM-AGENT",
        "observation_id": "OBS-1",
        "comparison_status": "insufficient_history",
        "evidence": {"reason": "Only baseline available"},
    }
    values.update(overrides)
    return SubmitReviewRequest(**values)


def test_submit_creates_pending_review_and_audit(setup):
    database, reviews = setup
    record = reviews.submit(request())

    assert record.status == "pending"
    assert reviews.get_pending()[0].request_id == record.request_id

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT action, actor_id FROM review_request_events
            WHERE request_id = ?
            """,
            (record.request_id,),
        ).fetchone()

    assert row == ("review.requested", "SYSTEM-AGENT")


def test_rejects_cross_case_observation_without_writing(setup):
    database, reviews = setup

    with pytest.raises(ValueError, match="does not belong"):
        reviews.submit(request(case_id="CASE-OTHER"))

    assert reviews.get_pending() == []

    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM review_request_events"
        ).fetchone()[0]
    assert count == 0


def test_review_audit_is_immutable(setup):
    database, reviews = setup
    record = reviews.submit(request())

    with pytest.raises(sqlite3.DatabaseError), database.connect() as connection:
        connection.execute(
            """
                UPDATE review_request_events SET actor_id = 'OTHER'
                WHERE request_id = ?
                """,
            (record.request_id,),
        )


def test_duplicate_submission_returns_existing_request(setup):
    database, reviews = setup

    first = reviews.submit(request())
    second = reviews.submit(request())

    assert first.request_id == second.request_id
    assert len(reviews.get_pending()) == 1

    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM review_request_events"
        ).fetchone()[0]

    assert count == 1


def test_conflicting_retry_is_rejected(setup):
    database, reviews = setup

    reviews.submit(request())

    with pytest.raises(ValueError, match="different evidence"):
        reviews.submit(request(evidence={"reason": "Changed evidence"}))

    assert len(reviews.get_pending()) == 1

    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM review_request_events"
        ).fetchone()[0]

    assert count == 1


def test_reinitialization_preserves_review_requests(setup):
    database, reviews = setup
    reviews.submit(request())

    reviews.initialize()
    assert len(ReviewRepository(database).get_pending()) == 1


def test_existing_database_receives_unique_index(setup):
    database, reviews = setup
    reviews.initialize()

    with database.connect() as connection:
        indexes = connection.execute("PRAGMA index_list('review_requests')").fetchall()

    assert any(
        row[1] == "idx_review_requests_observation" and row[2] == 1 for row in indexes
    )


def test_retry_does_not_replace_original_actor(setup):
    database, reviews = setup

    first = reviews.submit(request(actor_id="AGENT-1"))
    second = reviews.submit(request(actor_id="AGENT-2"))

    assert first.request_id == second.request_id

    with database.connect() as connection:
        actors = connection.execute(
            """
            SELECT actor_id FROM review_request_events
            WHERE request_id = ?
            """,
            (first.request_id,),
        ).fetchall()

    assert actors == [("AGENT-1",)]
