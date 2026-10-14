"""Persistent clinician review requests with atomic audit creation."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from tazama.storage.database import Database


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
                CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_review_requests_observation
                ON review_requests(observation_id)
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

    def submit(self, request: SubmitReviewRequest) -> ReviewRequest:
        """Atomically create a pending review and an immutable audit event."""
        if not request.case_id.strip() or not request.actor_id.strip():
            raise ValueError("Case ID and actor ID must not be blank")
        if not request.observation_id.strip():
            raise ValueError("Observation ID must not be blank")

        record = ReviewRequest(
            request_id=str(uuid4()),
            case_id=request.case_id,
            observation_id=request.observation_id,
            status="pending",
            created_at=datetime.now(UTC),
            comparison_status=request.comparison_status,
            evidence=request.evidence,
        )

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            observation = connection.execute(
                """
                SELECT case_id FROM observations
                WHERE observation_id = ?
                """,
                (request.observation_id,),
            ).fetchone()

            if observation is None or observation[0] != request.case_id:
                raise ValueError("Observation does not belong to the case")

            existing = connection.execute(
                """
                SELECT request_id, case_id, observation_id, status,
                       created_at, comparison_status, evidence_json
                FROM review_requests
                WHERE observation_id = ?
                """,
                (request.observation_id,),
            ).fetchone()

            if existing is not None:
                if (
                    existing[5] != request.comparison_status
                    or json.loads(existing[6]) != request.evidence
                ):
                    raise ValueError("Review already exists with different evidence")

                return ReviewRequest(
                    request_id=existing[0],
                    case_id=existing[1],
                    observation_id=existing[2],
                    status=existing[3],
                    created_at=datetime.fromisoformat(existing[4]),
                    comparison_status=existing[5],
                    evidence=json.loads(existing[6]),
                )

            try:
                connection.execute(
                    """
                    INSERT INTO review_requests (
                        request_id, case_id, observation_id, status,
                        created_at, comparison_status, evidence_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.request_id,
                        record.case_id,
                        record.observation_id,
                        record.status,
                        record.created_at.isoformat(),
                        record.comparison_status,
                        json.dumps(record.evidence),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO review_request_events (
                        event_id, request_id, case_id, actor_id,
                        action, occurred_at, details_json
                    ) VALUES (?, ?, ?, ?, 'review.requested', ?, ?)
                    """,
                    (
                        str(uuid4()),
                        record.request_id,
                        record.case_id,
                        request.actor_id,
                        record.created_at.isoformat(),
                        json.dumps(
                            {
                                "observation_id": record.observation_id,
                                "comparison_status": record.comparison_status,
                            }
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

    def get_pending(self) -> list[ReviewRequest]:
        """Return pending requests in chronological order."""
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT request_id, case_id, observation_id, status,
                       created_at, comparison_status, evidence_json
                FROM review_requests
                WHERE status = 'pending'
                ORDER BY created_at ASC, request_id ASC
                """
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
            )
            for row in rows
        ]
