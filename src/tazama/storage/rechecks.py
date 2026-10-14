import json
from uuid import uuid4

"""SQLite persistence for reassessment obligations."""

import sqlite3
from datetime import UTC, datetime

from tazama.audit.models import AuditEvent
from tazama.patients.reassessment import RecheckObligation
from tazama.storage.database import Database


def _append_transition_audit(
    connection: sqlite3.Connection,
    case_id: str,
    actor_id: str,
    action: str,
    entity_id: str,
    details: dict[str, str],
) -> None:
    """Write audit evidence using the caller's active transaction."""
    try:
        connection.execute(
            """
            INSERT INTO audit_events (
                event_id, case_id, actor_id, action,
                entity_id, occurred_at, details_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                case_id,
                actor_id,
                action,
                entity_id,
                datetime.now(UTC).isoformat(),
                json.dumps(details),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Reassessment audit persistence failed") from exc


class RecheckRepository:
    """Persist reassessment tasks without making clinical decisions."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def schedule(
        self,
        obligation: RecheckObligation,
        actor_id: str = "SYSTEM-UNATTRIBUTED",
    ) -> None:
        """Atomically schedule an obligation and record its audit event."""

        if not actor_id.strip():
            raise ValueError("Actor ID is required")

        if obligation.status != "scheduled":
            raise ValueError("Only scheduled obligations can be created")

        if obligation.due_at <= obligation.created_at:
            raise ValueError("Reassessment due time must follow creation time")

        audit_event = AuditEvent(
            case_id=obligation.case_id,
            actor_id=actor_id,
            action="recheck.scheduled",
            entity_id=obligation.obligation_id,
            details={
                "policy_reference": obligation.policy_reference,
            },
        )

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            baseline = connection.execute(
                """
                SELECT observation_id
                FROM observations
                WHERE case_id = ?
                  AND observation_type = 'baseline'
                """,
                (obligation.case_id,),
            ).fetchone()

            if baseline is None:
                raise ValueError(
                    "Cannot schedule reassessment without a baseline observation"
                )

            try:
                connection.execute(
                    """
                    INSERT INTO recheck_obligations (
                        obligation_id,
                        case_id,
                        due_at,
                        created_at,
                        status,
                        policy_reference
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obligation.obligation_id,
                        obligation.case_id,
                        obligation.due_at.isoformat(),
                        obligation.created_at.isoformat(),
                        obligation.status,
                        obligation.policy_reference,
                    ),
                )

                connection.execute(
                    """
                    INSERT INTO audit_events (
                        event_id,
                        case_id,
                        actor_id,
                        action,
                        entity_id,
                        occurred_at,
                        details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_event.event_id,
                        audit_event.case_id,
                        audit_event.actor_id,
                        audit_event.action,
                        audit_event.entity_id,
                        audit_event.occurred_at.isoformat(),
                        json.dumps(audit_event.details),
                    ),
                )

            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "Reassessment scheduling or audit persistence failed"
                ) from exc

    def get(self, obligation_id: str) -> RecheckObligation | None:
        """Retrieve a persisted reassessment obligation."""

        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT obligation_id, case_id, due_at,
                       created_at, status, policy_reference
                FROM recheck_obligations
                WHERE obligation_id = ?
                """,
                (obligation_id,),
            ).fetchone()

        if row is None:
            return None

        return RecheckObligation(
            obligation_id=row[0],
            case_id=row[1],
            due_at=datetime.fromisoformat(row[2]),
            created_at=datetime.fromisoformat(row[3]),
            status=row[4],
            policy_reference=row[5],
        )

    def get_due(self, as_of: datetime) -> list[RecheckObligation]:
        """Return outstanding reassessments due at or before a given time."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")

        cutoff = as_of.astimezone(UTC).isoformat()

        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT obligation_id, case_id, due_at,
                       created_at, status, policy_reference
                FROM recheck_obligations
                WHERE status = 'scheduled'
                  AND due_at <= ?
                ORDER BY due_at ASC, obligation_id ASC
                """,
                (cutoff,),
            ).fetchall()

        return [
            RecheckObligation(
                obligation_id=row[0],
                case_id=row[1],
                due_at=datetime.fromisoformat(row[2]),
                created_at=datetime.fromisoformat(row[3]),
                status=row[4],
                policy_reference=row[5],
            )
            for row in rows
        ]

    def complete(
        self,
        obligation_id: str,
        observation_id: str,
        completed_at: datetime,
        actor_id: str = "SYSTEM-UNATTRIBUTED",
    ) -> None:
        """Complete an obligation using an existing recheck observation."""

        if not actor_id.strip():
            raise ValueError("Actor ID is required")

        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("completed_at must include a timezone")

        completed_at = completed_at.astimezone(UTC)

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            obligation = connection.execute(
                """
                SELECT case_id, status, created_at
                FROM recheck_obligations
                WHERE obligation_id = ?
                """,
                (obligation_id,),
            ).fetchone()

            if obligation is None:
                raise ValueError("Reassessment obligation not found")

            case_id, status, created_at_raw = obligation

            if status != "scheduled":
                raise ValueError("Only scheduled obligations can be completed")

            created_at = datetime.fromisoformat(created_at_raw)

            observation = connection.execute(
                """
                SELECT case_id, observation_type, recorded_at, received_at
                FROM observations
                WHERE observation_id = ?
                """,
                (observation_id,),
            ).fetchone()

            if observation is None:
                raise ValueError("Recheck observation not found")

            (
                observation_case_id,
                observation_type,
                recorded_at_raw,
                received_at_raw,
            ) = observation

            if observation_case_id != case_id:
                raise ValueError("Observation belongs to a different patient case")

            if observation_type != "recheck":
                raise ValueError("Completion requires a recheck observation")

            recorded_at = datetime.fromisoformat(recorded_at_raw)
            received_at = datetime.fromisoformat(received_at_raw)

            if recorded_at < created_at:
                raise ValueError(
                    "Recheck observation predates the reassessment obligation"
                )

            if completed_at < received_at:
                raise ValueError("Completion cannot precede receipt of the observation")

            existing_use = connection.execute(
                """
                SELECT obligation_id
                FROM recheck_obligations
                WHERE completed_observation_id = ?
                """,
                (observation_id,),
            ).fetchone()

            if existing_use is not None:
                raise ValueError(
                    "Recheck observation already used to complete an obligation"
                )

            try:
                cursor = connection.execute(
                    """
                    UPDATE recheck_obligations
                    SET status = 'completed',
                        completed_observation_id = ?,
                        completed_at = ?
                    WHERE obligation_id = ?
                      AND status = 'scheduled'
                    """,
                    (
                        observation_id,
                        completed_at.isoformat(),
                        obligation_id,
                    ),
                )

                if cursor.rowcount != 1:
                    raise ValueError("Reassessment state changed unexpectedly")

            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "Reassessment completion violated a database constraint"
                ) from exc

            _append_transition_audit(
                connection=connection,
                case_id=case_id,
                actor_id=actor_id,
                action="recheck.completed",
                entity_id=obligation_id,
                details={"observation_id": observation_id},
            )

    def cancel(
        self,
        obligation_id: str,
        reason: str,
        actor_id: str,
        cancelled_at: datetime,
    ) -> None:
        """Cancel a scheduled reassessment with an explicit reason."""

        if not obligation_id.strip():
            raise ValueError("Obligation ID is required")

        if not reason.strip():
            raise ValueError("Cancellation reason is required")

        if not actor_id.strip():
            raise ValueError("Actor ID is required")

        if cancelled_at.tzinfo is None or cancelled_at.utcoffset() is None:
            raise ValueError("cancelled_at must include a timezone")

        cancelled_at = cancelled_at.astimezone(UTC)

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            row = connection.execute(
                """
                SELECT status, created_at
                FROM recheck_obligations
                WHERE obligation_id = ?
                """,
                (obligation_id,),
            ).fetchone()

            if row is None:
                raise ValueError("Reassessment obligation not found")

            audit_case_id = connection.execute(
                "SELECT case_id FROM recheck_obligations WHERE obligation_id = ?",
                (obligation_id,),
            ).fetchone()[0]
            status, created_at_raw = row
            created_at = datetime.fromisoformat(created_at_raw)

            if status != "scheduled":
                raise ValueError("Only scheduled obligations can be cancelled")

            if cancelled_at < created_at:
                raise ValueError("Cancellation cannot predate obligation creation")

            cursor = connection.execute(
                """
                UPDATE recheck_obligations
                SET status = 'cancelled',
                    cancelled_at = ?,
                    cancellation_reason = ?
                WHERE obligation_id = ?
                  AND status = 'scheduled'
                """,
                (
                    cancelled_at.isoformat(),
                    reason.strip(),
                    obligation_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError("Reassessment state changed unexpectedly")

            _append_transition_audit(
                connection=connection,
                case_id=audit_case_id,
                actor_id=actor_id,
                action="recheck.cancelled",
                entity_id=obligation_id,
                details={"reason": reason.strip()},
            )
