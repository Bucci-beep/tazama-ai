"""Persistent audit event repository."""

import json
import sqlite3
from datetime import datetime

from tazama.audit.models import AuditEvent
from tazama.storage.database import Database


class AuditRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def append(self, event: AuditEvent) -> None:
        """Persist a new audit event without modifying existing events."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            try:
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
                        event.event_id,
                        event.case_id,
                        event.actor_id,
                        event.action,
                        event.entity_id,
                        event.occurred_at.isoformat(),
                        json.dumps(event.details),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Audit event could not be saved") from exc

    def get_for_case(self, case_id: str) -> list[AuditEvent]:
        """Return audit events in chronological order."""

        if not case_id.strip():
            raise ValueError("Case ID is required")

        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    event_id,
                    case_id,
                    actor_id,
                    action,
                    entity_id,
                    occurred_at,
                    details_json
                FROM audit_events
                WHERE case_id = ?
                ORDER BY occurred_at ASC, event_id ASC
                """,
                (case_id,),
            ).fetchall()

        return [
            AuditEvent(
                event_id=row[0],
                case_id=row[1],
                actor_id=row[2],
                action=row[3],
                entity_id=row[4],
                occurred_at=datetime.fromisoformat(row[5]),
                details=json.loads(row[6]),
            )
            for row in rows
        ]
