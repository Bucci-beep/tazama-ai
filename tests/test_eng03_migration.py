"""ENG03 migration safety regression tests."""

from datetime import UTC, datetime

from tazama.mcp.contracts import PatientObservations
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import (
    ReviewRepository,
    SubmitAttestation,
    SubmitReviewRequest,
)


def test_legacy_review_upgrade_preserves_audit_and_attestation(tmp_path):
    database = Database(tmp_path / "legacy.sqlite3")
    database.initialize()

    reviews = ReviewRepository(database)
    reviews.initialize()

    ObservationRepository(database).save(
        ObservationRecord(
            observation_id="OBS-LEGACY",
            case_id="CASE-LEGACY",
            recorded_at=datetime(2026, 10, 14, tzinfo=UTC),
            observation_type="baseline",
            observations=PatientObservations(heart_rate_bpm=80.0),
        )
    )

    original = reviews.submit(
        SubmitReviewRequest(
            case_id="CASE-LEGACY",
            actor_id="SYSTEM-AGENT",
            observation_id="OBS-LEGACY",
            comparison_status="insufficient_history",
            evidence={"signs_assessed": False},
        )
    )

    attestation = reviews.attest(
        SubmitAttestation(
            request_id=original.request_id,
            clinician_id="DEMO-CLINICIAN-1",
            action="approved",
        )
    )

    with database.connect() as connection:
        original_event = connection.execute(
            """
            SELECT event_id, request_id, actor_id, details_json
            FROM review_request_events
            WHERE request_id = ?
            """,
            (original.request_id,),
        ).fetchone()

    reviews.initialize()

    with database.connect() as connection:
        migrated = connection.execute(
            """
            SELECT request_id, revision, supersedes_request_id,
                   evidence_json
            FROM review_requests
            WHERE observation_id = ?
            """,
            ("OBS-LEGACY",),
        ).fetchone()

        preserved_event = connection.execute(
            """
            SELECT event_id, request_id, actor_id, details_json
            FROM review_request_events
            WHERE request_id = ?
            """,
            (original.request_id,),
        ).fetchone()

        preserved_attestation = connection.execute(
            """
            SELECT event_id, request_id, evidence_json
            FROM review_attestations
            WHERE request_id = ?
            """,
            (original.request_id,),
        ).fetchone()

        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert migrated[0] == original.request_id
    assert migrated[1] == 1
    assert migrated[2] is None
    assert preserved_event == original_event
    assert preserved_attestation == (
        attestation.event_id,
        original.request_id,
        attestation.evidence_json,
    )
    assert foreign_key_errors == []


def test_revision_constraint_rejects_duplicate_revision(tmp_path):
    database = Database(tmp_path / "revision.sqlite3")
    database.initialize()

    reviews = ReviewRepository(database)
    reviews.initialize()

    with database.connect() as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(review_requests)"
            )
        }

    assert "revision" in columns
    assert "supersedes_request_id" in columns

    with database.connect() as connection:
        indexes = connection.execute(
            "PRAGMA index_list(review_requests)"
        ).fetchall()

        unique_columns = [
            [
                column[2]
                for column in connection.execute(
                    f"PRAGMA index_info({row[1]})"
                )
            ]
            for row in indexes
            if row[2] == 1
        ]

    assert ["observation_id", "revision"] in unique_columns
