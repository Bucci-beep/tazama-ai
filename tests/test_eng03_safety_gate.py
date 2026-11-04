"""ENG03 safety gate: populated legacy migration, racing writers, immutable history."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest

from tazama.mcp.contracts import PatientObservations
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRepository, SubmitReviewRequest


def _observation(database, observation_id="OBS-GATE"):
    ObservationRepository(database).save(
        ObservationRecord(
            observation_id=observation_id,
            case_id="CASE-GATE",
            recorded_at=datetime(2026, 10, 14, tzinfo=UTC),
            observation_type="baseline",
            observations=PatientObservations(heart_rate_bpm=80.0),
        )
    )


def _request(evidence, expected=None):
    return SubmitReviewRequest(
        case_id="CASE-GATE",
        actor_id="SYSTEM-AGENT",
        observation_id="OBS-GATE",
        comparison_status="insufficient_history",
        evidence=evidence,
        expected_current_request_id=expected,
    )


def test_populated_original_schema_upgrade_preserves_history(tmp_path):
    database = Database(tmp_path / "legacy-populated.sqlite3")
    database.initialize()
    _observation(database)
    created = "2026-10-14T12:00:00+00:00"
    original_evidence = json.dumps({"signs_assessed": False}, sort_keys=True)
    original_details = json.dumps({"observation_id": "OBS-GATE"})
    attested_evidence = json.dumps({"identity_assurance": "asserted_demo_identity"})
    with database.connect() as connection:
        connection.execute("""CREATE TABLE review_requests (
            request_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL CHECK(length(trim(case_id)) > 0),
            observation_id TEXT NOT NULL UNIQUE REFERENCES observations(observation_id),
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status = 'pending'),
            created_at TEXT NOT NULL,
            comparison_status TEXT NOT NULL,
            evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json))
        )""")
        connection.execute("""CREATE TABLE review_request_events (
            event_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL REFERENCES review_requests(request_id),
            case_id TEXT NOT NULL,
            actor_id TEXT NOT NULL CHECK(length(trim(actor_id)) > 0),
            action TEXT NOT NULL CHECK(action = 'review.requested'),
            occurred_at TEXT NOT NULL,
            details_json TEXT NOT NULL CHECK(json_valid(details_json))
        )""")
        connection.execute("""CREATE TABLE review_attestations (
            event_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE REFERENCES review_requests(request_id),
            case_id TEXT NOT NULL,
            clinician_id TEXT NOT NULL CHECK(length(trim(clinician_id)) > 0),
            action TEXT NOT NULL CHECK(action IN ('approved', 'rejected')),
            identity_assurance TEXT NOT NULL CHECK(identity_assurance = 'asserted_demo_identity'),
            evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
            occurred_at TEXT NOT NULL
        )""")
        connection.execute(
            """INSERT INTO review_requests VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "REVIEW-OLD",
                "CASE-GATE",
                "OBS-GATE",
                "pending",
                created,
                "insufficient_history",
                original_evidence,
            ),
        )
        connection.execute(
            """INSERT INTO review_request_events VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "EVENT-OLD",
                "REVIEW-OLD",
                "CASE-GATE",
                "SYSTEM-AGENT",
                "review.requested",
                created,
                original_details,
            ),
        )
        connection.execute(
            """INSERT INTO review_attestations VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "ATTEST-OLD",
                "REVIEW-OLD",
                "CASE-GATE",
                "DEMO-CLINICIAN",
                "approved",
                "asserted_demo_identity",
                attested_evidence,
                created,
            ),
        )

    with database.connect() as connection:
        before = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("review_request_events", "review_attestations")
        }

    reviews = ReviewRepository(database)
    reviews.initialize()
    reviews.initialize()
    with database.connect() as connection:
        row = connection.execute(
            """SELECT request_id, revision, supersedes_request_id,
            evidence_json FROM review_requests WHERE observation_id = ?""",
            ("OBS-GATE",),
        ).fetchone()
        assert row == ("REVIEW-OLD", 1, None, original_evidence)
        for table, rows in before.items():
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == rows
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert reviews.get_by_observation_id("OBS-GATE").request_id == "REVIEW-OLD"


def test_competing_revision_submissions_only_one_wins(tmp_path):
    database = Database(tmp_path / "concurrent.sqlite3")
    database.initialize()
    _observation(database)
    reviews = ReviewRepository(database)
    reviews.initialize()
    first = reviews.submit(_request({"signs_assessed": False}))
    gate = Barrier(2)

    def submit_changed(reason):
        gate.wait(timeout=5)
        try:
            result = ReviewRepository(database).submit(
                _request({"signs_assessed": True, "reason": reason}, first.request_id)
            )
            return ("ok", result.request_id)
        except ValueError as exc:
            return ("rejected", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(submit_changed, "A")
        b = pool.submit(submit_changed, "B")
        outcomes = [a.result(timeout=15), b.result(timeout=15)]
    assert sorted(status for status, _ in outcomes) == ["ok", "rejected"]
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT revision, supersedes_request_id
            FROM review_requests WHERE observation_id = ? ORDER BY revision""",
            ("OBS-GATE",),
        ).fetchall()
        assert rows == [(1, None), (2, first.request_id)]
        assert (
            connection.execute("SELECT COUNT(*) FROM review_request_events").fetchone()[
                0
            ]
            == 2
        )


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_review_history_is_database_immutable(tmp_path, operation):
    database = Database(tmp_path / "immutable.sqlite3")
    database.initialize()
    _observation(database)
    reviews = ReviewRepository(database)
    reviews.initialize()
    first = reviews.submit(_request({"signs_assessed": False}))
    reviews.submit(_request({"signs_assessed": True}, first.request_id))
    with pytest.raises(sqlite3.DatabaseError), database.connect() as connection:
        if operation == "update":
            connection.execute(
                """UPDATE review_requests SET evidence_json = ?
                    WHERE request_id = ?""",
                ('{"tampered":true}', first.request_id),
            )
        else:
            connection.execute(
                "DELETE FROM review_requests WHERE request_id = ?",
                (first.request_id,),
            )
    with database.connect() as connection:
        assert connection.execute(
            """SELECT evidence_json FROM review_requests
            WHERE request_id = ?""",
            (first.request_id,),
        ).fetchone() == (json.dumps({"signs_assessed": False}),)
        assert (
            connection.execute("SELECT COUNT(*) FROM review_requests").fetchone()[0]
            == 2
        )
