"""SQLite connection management for Tazama."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Database:
    """Manage connections to a local SQLite database."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection and manage its transaction."""

        connection = sqlite3.connect(self.database_path)

        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the observations table if it does not exist."""

        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    observation_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    observation_type TEXT NOT NULL
                        CHECK (
                            observation_type IN ('baseline', 'recheck')
                        ),
                    recorded_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    observations_json TEXT NOT NULL,
                    CHECK (length(case_id) > 0)
                )
                """
            )

            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_one_baseline_per_case
                ON observations(case_id)
                WHERE observation_type = 'baseline'
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_observations_case_time
                ON observations(case_id, recorded_at)
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS recheck_obligations (
                    obligation_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'scheduled'
                        CHECK (
                            status IN (
                                'scheduled',
                                'completed',
                                'cancelled'
                            )
                        ),
                    policy_reference TEXT NOT NULL,
                    completed_observation_id TEXT,
                    completed_at TEXT,
                    cancelled_at TEXT,
                    cancellation_reason TEXT,
                    CHECK (length(case_id) > 0),
                    CHECK (length(policy_reference) > 0),
                    FOREIGN KEY (completed_observation_id)
                        REFERENCES observations(observation_id),
                    CHECK (
                        (
                            status = 'scheduled'
                            AND completed_observation_id IS NULL
                            AND completed_at IS NULL
                            AND cancelled_at IS NULL
                            AND cancellation_reason IS NULL
                        )
                        OR
                        (
                            status = 'completed'
                            AND completed_observation_id IS NOT NULL
                            AND completed_at IS NOT NULL
                            AND cancelled_at IS NULL
                            AND cancellation_reason IS NULL
                        )
                        OR
                        (
                            status = 'cancelled'
                            AND completed_observation_id IS NULL
                            AND completed_at IS NULL
                            AND cancelled_at IS NOT NULL
                            AND cancellation_reason IS NOT NULL
                            AND length(cancellation_reason) > 0
                        )
                    )
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_recheck_obligations_status_due
                ON recheck_obligations(status, due_at)
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL
                        CHECK (length(trim(case_id)) > 0),
                    actor_id TEXT NOT NULL
                        CHECK (length(trim(actor_id)) > 0),
                    action TEXT NOT NULL
                        CHECK (
                            action IN (
                                'recheck.scheduled',
                                'recheck.completed',
                                'recheck.cancelled'
                            )
                        ),
                    entity_id TEXT NOT NULL
                        CHECK (length(trim(entity_id)) > 0),
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL
                        CHECK (json_valid(details_json)),
                    FOREIGN KEY (entity_id)
                        REFERENCES recheck_obligations(obligation_id)
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_audit_events_case_time
                ON audit_events(case_id, occurred_at)
                """
            )

            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS
                    prevent_audit_event_update
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Audit events cannot be updated'
                    );
                END
                """
            )

            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS
                    prevent_audit_event_delete
                BEFORE DELETE ON audit_events
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Audit events cannot be deleted'
                    );
                END
                """
            )
