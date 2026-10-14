import sqlite3

import pytest

from tazama.storage.database import Database


def test_database_connection_creates_file(tmp_path):
    database_path = tmp_path / "tazama.db"
    database = Database(database_path)

    with database.connect() as connection:
        connection.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")

    assert database_path.exists()


def test_database_commits_successful_transaction(tmp_path):
    database = Database(tmp_path / "tazama.db")

    with database.connect() as connection:
        connection.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO example (id) VALUES (1)")

    with database.connect() as connection:
        result = connection.execute("SELECT COUNT(*) FROM example").fetchone()

    assert result[0] == 1


def test_database_rolls_back_failed_transaction(tmp_path):
    database = Database(tmp_path / "tazama.db")

    with database.connect() as connection:
        connection.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")

    with pytest.raises(RuntimeError), database.connect() as connection:
        connection.execute("INSERT INTO example (id) VALUES (1)")
        raise RuntimeError("Simulated failure")

    with database.connect() as connection:
        result = connection.execute("SELECT COUNT(*) FROM example").fetchone()

    assert result[0] == 0


def test_foreign_keys_are_enabled(tmp_path):
    database = Database(tmp_path / "tazama.db")

    with database.connect() as connection:
        enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]

    assert enabled == 1


def test_initialize_creates_observations_table(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    with database.connect() as connection:
        result = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'observations'
            """
        ).fetchone()

    assert result is not None


def test_initialize_is_idempotent(tmp_path):
    database = Database(tmp_path / "tazama.db")

    database.initialize()
    database.initialize()

    with database.connect() as connection:
        result = connection.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table' AND name = 'observations'
            """
        ).fetchone()

    assert result[0] == 1


def test_database_rejects_multiple_baselines(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO observations
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "OBS-001",
                "JOSEPH-001",
                "baseline",
                "2026-10-13T08:15:00+00:00",
                "2026-10-13T08:16:00+00:00",
                "{}",
            ),
        )

    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
        connection.execute(
            """
                INSERT INTO observations
                VALUES (?, ?, ?, ?, ?, ?)
                """,
            (
                "OBS-002",
                "JOSEPH-001",
                "baseline",
                "2026-10-13T08:20:00+00:00",
                "2026-10-13T08:21:00+00:00",
                "{}",
            ),
        )


def test_initialize_creates_recheck_obligations_table(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    with database.connect() as connection:
        result = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'recheck_obligations'
            """
        ).fetchone()

    assert result is not None


def test_recheck_obligation_requires_policy_reference(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
        connection.execute(
            """
                INSERT INTO recheck_obligations (
                    obligation_id,
                    case_id,
                    due_at,
                    created_at,
                    policy_reference
                )
                VALUES (?, ?, ?, ?, ?)
                """,
            (
                "RECHECK-001",
                "JOSEPH-001",
                "2026-10-13T09:00:00+00:00",
                "2026-10-13T08:30:00+00:00",
                "",
            ),
        )


def test_recheck_cannot_be_completed_without_observation(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
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
                "RECHECK-002",
                "JOSEPH-001",
                "2026-10-13T09:00:00+00:00",
                "2026-10-13T08:30:00+00:00",
                "completed",
                "DEMO-POLICY-001",
            ),
        )


def test_initialize_creates_audit_events_table(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    with database.connect() as connection:
        result = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'audit_events'
            """
        ).fetchone()

    assert result is not None


def test_audit_event_rejects_unknown_action(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
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
                "EVENT-001",
                "JOSEPH-001",
                "NURSE-001",
                "priority.changed",
                "RECHECK-001",
                "2026-10-14T09:00:00+00:00",
                "{}",
            ),
        )


def test_audit_event_rejects_invalid_json(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
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
                "EVENT-002",
                "JOSEPH-001",
                "NURSE-001",
                "recheck.scheduled",
                "RECHECK-001",
                "2026-10-14T09:00:00+00:00",
                "{invalid-json}",
            ),
        )
