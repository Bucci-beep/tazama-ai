"""Persistent clinician review requests with atomic audit creation."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from tazama.storage.database import Database


def deterministic_evidence(evidence: dict) -> dict:
    """Return the fields that define clinical review idempotency."""
    return {
        key: value
        for key, value in evidence.items()
        if key
        not in {
            "explanation",
            "explanation_error",
            "workflow_provenance",
        }
    }


class SubmitReviewRequest(BaseModel):
    """Evidence submitted for review, never an approval decision."""

    model_config = ConfigDict(extra="forbid", strict=True)

    case_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    comparison_status: Literal[
        "differences_found",
        "no_differences",
        "insufficient_history",
        "untrusted_reading",
        "tool_unavailable",
    ]
    evidence: dict
    expected_current_request_id: str | None = Field(
        default=None,
        min_length=1,
    )


class ReviewRequest(BaseModel):
    """Persisted pending request."""

    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str
    case_id: str
    observation_id: str
    status: Literal["pending"]
    created_at: datetime
    comparison_status: str
    evidence: dict
    revision: int = Field(default=1, ge=1)
    supersedes_request_id: str | None = None


class SubmitAttestation(BaseModel):
    """Demo-only asserted clinician identity and disposition."""

    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str = Field(min_length=1)
    clinician_id: str = Field(min_length=1)
    action: Literal["approved", "rejected"]
    identity_assurance: Literal["asserted_demo_identity"] = "asserted_demo_identity"


class ReviewAttestation(SubmitAttestation):
    event_id: str
    case_id: str
    evidence_json: str
    occurred_at: datetime


class ReviewRepository:
    """Create and retrieve review requests without approving them."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def initialize(self) -> None:
        """Create review tables without changing existing audit constraints."""
        with self.database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS review_requests (
                    request_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL CHECK(length(trim(case_id)) > 0),
                    observation_id TEXT NOT NULL UNIQUE
                        REFERENCES observations(observation_id),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status = 'pending'),
                    created_at TEXT NOT NULL,
                    comparison_status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json))
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS review_attestations (
                    event_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE
                        REFERENCES review_requests(request_id),
                    case_id TEXT NOT NULL,
                    clinician_id TEXT NOT NULL
                        CHECK(length(trim(clinician_id)) > 0),
                    action TEXT NOT NULL CHECK(action IN ('approved', 'rejected')),
                    identity_assurance TEXT NOT NULL
                        CHECK(identity_assurance = 'asserted_demo_identity'),
                    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
                    occurred_at TEXT NOT NULL
                )
                """
            )
            for operation in ("UPDATE", "DELETE"):
                connection.execute(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS
                        prevent_review_attestation_{operation.lower()}
                    BEFORE {operation} ON review_attestations
                    BEGIN
                        SELECT RAISE(ABORT, 'Review attestations are immutable');
                    END
                    """
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_review_requests_queue
                ON review_requests(status, created_at)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS review_request_events (
                    event_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL
                        REFERENCES review_requests(request_id),
                    case_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL
                        CHECK(length(trim(actor_id)) > 0),
                    action TEXT NOT NULL
                        CHECK(action = 'review.requested'),
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL CHECK(json_valid(details_json))
                )
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_review_event_update
                BEFORE UPDATE ON review_request_events
                BEGIN
                    SELECT RAISE(ABORT, 'Review audit events cannot be updated');
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_review_event_delete
                BEFORE DELETE ON review_request_events
                BEGIN
                    SELECT RAISE(ABORT, 'Review audit events cannot be deleted');
                END
                """
            )

        self._migrate_review_revisions()
        with self.database.connect() as connection:
            for operation in ("UPDATE", "DELETE"):
                connection.execute(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS
                        prevent_review_request_{operation.lower()}
                    BEFORE {operation} ON review_requests
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'Review requests are immutable'
                        );
                    END
                    """
                )

    def _migrate_review_revisions(self) -> None:
        """Atomically upgrade legacy reviews while preserving dependent records."""
        connection = sqlite3.connect(self.database.database_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(review_requests)")
            }
            legacy_columns = {
                "request_id",
                "case_id",
                "observation_id",
                "status",
                "created_at",
                "comparison_status",
                "evidence_json",
            }
            if {"revision", "supersedes_request_id"} <= columns:
                problems = connection.execute("PRAGMA foreign_key_check").fetchall()
                if problems:
                    raise RuntimeError(f"Existing foreign key violations: {problems}")
                return
            if columns != legacy_columns:
                raise RuntimeError("Unknown review schema; migration refused")

            existing_problems = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if existing_problems:
                raise RuntimeError(
                    f"Legacy database has foreign key violations: {existing_problems}"
                )

            connection.execute("PRAGMA foreign_keys = OFF")
            if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 0:
                raise RuntimeError("Could not disable FKs for atomic table rebuild")

            connection.execute("BEGIN IMMEDIATE")
            try:
                original_count = connection.execute(
                    "SELECT COUNT(*) FROM review_requests"
                ).fetchone()[0]

                connection.execute("""
                    CREATE TABLE eng03_review_requests_new (
                        request_id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL CHECK(length(trim(case_id)) > 0),
                        observation_id TEXT NOT NULL
                            REFERENCES observations(observation_id),
                        revision INTEGER NOT NULL DEFAULT 1
                            CHECK(revision >= 1),
                        supersedes_request_id TEXT
                            REFERENCES review_requests(request_id),
                        status TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status = 'pending'),
                        created_at TEXT NOT NULL,
                        comparison_status TEXT NOT NULL,
                        evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
                        UNIQUE(observation_id, revision)
                    )
                """)

                connection.execute("""
                    INSERT INTO eng03_review_requests_new (
                        request_id, case_id, observation_id, revision,
                        supersedes_request_id, status, created_at,
                        comparison_status, evidence_json
                    )
                    SELECT request_id, case_id, observation_id, 1, NULL,
                           status, created_at, comparison_status, evidence_json
                    FROM review_requests
                """)

                copied_count = connection.execute(
                    "SELECT COUNT(*) FROM eng03_review_requests_new"
                ).fetchone()[0]
                if copied_count != original_count:
                    raise RuntimeError("Review row count mismatch")

                connection.execute("DROP TABLE review_requests")
                connection.execute(
                    "ALTER TABLE eng03_review_requests_new RENAME TO review_requests"
                )
                connection.execute("""
                    CREATE INDEX idx_review_requests_queue
                    ON review_requests(status, created_at)
                """)

                problems = connection.execute("PRAGMA foreign_key_check").fetchall()
                if problems:
                    raise RuntimeError(f"Migration foreign key violations: {problems}")

                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.execute("PRAGMA foreign_keys = ON")
                if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                    raise RuntimeError("Foreign key enforcement was not restored")
        finally:
            connection.close()

    def submit(self, request: SubmitReviewRequest) -> ReviewRequest:
        """Create a review or an immutable successor using compare-and-swap."""
        if (
            not request.case_id.strip()
            or not request.actor_id.strip()
            or not request.observation_id.strip()
        ):
            raise ValueError("Review identifiers must not be blank")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            observation = connection.execute(
                "SELECT case_id FROM observations WHERE observation_id = ?",
                (request.observation_id,),
            ).fetchone()
            if observation is None or observation[0] != request.case_id:
                raise ValueError("Observation does not belong to the case")
            latest = connection.execute(
                """SELECT observation_id FROM observations
                   WHERE case_id = ?
                   ORDER BY recorded_at DESC, observation_id DESC LIMIT 1""",
                (request.case_id,),
            ).fetchone()
            if latest is None or latest[0] != request.observation_id:
                raise ValueError("OBSERVATION_SUPERSEDED")
            current = connection.execute(
                """SELECT request_id, case_id, observation_id, status, created_at,
                          comparison_status, evidence_json, revision, supersedes_request_id
                   FROM review_requests WHERE observation_id = ?
                   ORDER BY revision DESC LIMIT 1""",
                (request.observation_id,),
            ).fetchone()
            if current is not None:
                unchanged = current[
                    5
                ] == request.comparison_status and deterministic_evidence(
                    json.loads(current[6])
                ) == deterministic_evidence(request.evidence)
                if unchanged:
                    if request.expected_current_request_id not in (None, current[0]):
                        raise ValueError("Stale review precondition")
                    return ReviewRequest(
                        request_id=current[0],
                        case_id=current[1],
                        observation_id=current[2],
                        status=current[3],
                        created_at=datetime.fromisoformat(current[4]),
                        comparison_status=current[5],
                        evidence=json.loads(current[6]),
                        revision=current[7],
                        supersedes_request_id=current[8],
                    )
                if request.expected_current_request_id != current[0]:
                    raise ValueError(
                        "Review already exists with different evidence or stale precondition"
                    )
                revision = current[7] + 1
                supersedes = current[0]
            else:
                if request.expected_current_request_id is not None:
                    raise ValueError("No current review matches precondition")
                revision = 1
                supersedes = None
            record = ReviewRequest(
                request_id=str(uuid4()),
                case_id=request.case_id,
                observation_id=request.observation_id,
                status="pending",
                created_at=datetime.now(UTC),
                comparison_status=request.comparison_status,
                evidence=request.evidence,
                revision=revision,
                supersedes_request_id=supersedes,
            )
            try:
                connection.execute(
                    """INSERT INTO review_requests
                       (request_id, case_id, observation_id, revision,
                        supersedes_request_id, status, created_at,
                        comparison_status, evidence_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.request_id,
                        record.case_id,
                        record.observation_id,
                        record.revision,
                        record.supersedes_request_id,
                        record.status,
                        record.created_at.isoformat(),
                        record.comparison_status,
                        json.dumps(record.evidence, sort_keys=True),
                    ),
                )
                connection.execute(
                    """INSERT INTO review_request_events
                       (event_id, request_id, case_id, actor_id, action,
                        occurred_at, details_json)
                       VALUES (?, ?, ?, ?, 'review.requested', ?, ?)""",
                    (
                        str(uuid4()),
                        record.request_id,
                        record.case_id,
                        request.actor_id,
                        datetime.now(UTC).isoformat(),
                        json.dumps(
                            {
                                "observation_id": record.observation_id,
                                "comparison_status": record.comparison_status,
                                "revision": record.revision,
                                "supersedes_request_id": record.supersedes_request_id,
                            },
                            sort_keys=True,
                        ),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Review request persistence failed") from exc
            return record

    def attest(self, request: SubmitAttestation) -> ReviewAttestation:
        """Append one demo attestation without changing request or priority state."""
        if not request.request_id.strip() or not request.clinician_id.strip():
            raise ValueError("Request and clinician IDs must not be blank")

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            review = connection.execute(
                """
                SELECT case_id, evidence_json FROM review_requests
                WHERE request_id = ?
                """,
                (request.request_id,),
            ).fetchone()
            if review is None:
                raise ValueError("Review request not found")

            existing = connection.execute(
                """
                SELECT event_id, request_id, case_id, clinician_id, action,
                       identity_assurance, evidence_json, occurred_at
                FROM review_attestations WHERE request_id = ?
                """,
                (request.request_id,),
            ).fetchone()
            if existing is not None:
                if existing[3:6] != (
                    request.clinician_id,
                    request.action,
                    request.identity_assurance,
                ):
                    raise ValueError(
                        "Review request already has a conflicting attestation"
                    )
                return ReviewAttestation(
                    event_id=existing[0],
                    request_id=existing[1],
                    case_id=existing[2],
                    clinician_id=existing[3],
                    action=existing[4],
                    identity_assurance=existing[5],
                    evidence_json=existing[6],
                    occurred_at=datetime.fromisoformat(existing[7]),
                )

            current = connection.execute(
                """SELECT request_id FROM review_requests
                   WHERE observation_id = (
                       SELECT observation_id FROM review_requests WHERE request_id = ?
                   )
                   ORDER BY revision DESC LIMIT 1""",
                (request.request_id,),
            ).fetchone()
            if current is None or current[0] != request.request_id:
                raise ValueError("Cannot attest a superseded review revision")

            record = ReviewAttestation(
                event_id=str(uuid4()),
                request_id=request.request_id,
                case_id=review[0],
                clinician_id=request.clinician_id,
                action=request.action,
                identity_assurance=request.identity_assurance,
                evidence_json=review[1],
                occurred_at=datetime.now(UTC),
            )
            connection.execute(
                """
                INSERT INTO review_attestations (
                    event_id, request_id, case_id, clinician_id, action,
                    identity_assurance, evidence_json, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.event_id,
                    record.request_id,
                    record.case_id,
                    record.clinician_id,
                    record.action,
                    record.identity_assurance,
                    record.evidence_json,
                    record.occurred_at.isoformat(),
                ),
            )
        return record

    def get_by_observation_id(self, observation_id: str) -> ReviewRequest | None:
        """Return the current (highest-numbered) revision."""
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT request_id, case_id, observation_id, status, created_at,
                          comparison_status, evidence_json, revision, supersedes_request_id
                   FROM review_requests WHERE observation_id = ?
                   ORDER BY revision DESC LIMIT 1""",
                (observation_id,),
            ).fetchone()
        if row is None:
            return None
        return ReviewRequest(
            request_id=row[0],
            case_id=row[1],
            observation_id=row[2],
            status=row[3],
            created_at=datetime.fromisoformat(row[4]),
            comparison_status=row[5],
            evidence=json.loads(row[6]),
            revision=row[7],
            supersedes_request_id=row[8],
        )

    def get_pending(self) -> list[ReviewRequest]:
        """Return only the latest pending review for each observation."""
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT r.request_id, r.case_id, r.observation_id, r.status,
                          r.created_at, r.comparison_status, r.evidence_json,
                          r.revision, r.supersedes_request_id
                   FROM review_requests AS r
                   WHERE r.status = 'pending' AND NOT EXISTS (
                       SELECT 1 FROM review_requests AS newer
                       WHERE newer.observation_id = r.observation_id
                         AND newer.revision > r.revision
                   )
                   ORDER BY r.created_at ASC, r.request_id ASC"""
            ).fetchall()
        return [
            ReviewRequest(
                request_id=row[0],
                case_id=row[1],
                observation_id=row[2],
                status=row[3],
                created_at=datetime.fromisoformat(row[4]),
                comparison_status=row[5],
                evidence=json.loads(row[6]),
                revision=row[7],
                supersedes_request_id=row[8],
            )
            for row in rows
        ]
