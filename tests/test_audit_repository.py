import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from tazama.audit.models import AuditEvent
from tazama.storage.audit import AuditRepository
from tazama.storage.database import Database


@pytest.fixture
def audit_setup(tmp_path):
    database = Database(tmp_path / "audit.db")
    database.initialize()

    created_at = datetime.now(UTC)
    due_at = created_at + timedelta(minutes=30)

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO observations (
                observation_id,
                case_id,
                observation_type,
                recorded_at,
                received_at,
                observations_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "OBS-001",
                "CASE-001",
                "baseline",
                created_at.isoformat(),
                created_at.isoformat(),
                "{}",
            ),
        )

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
                "RECHECK-001",
                "CASE-001",
                due_at.isoformat(),
                created_at.isoformat(),
                "scheduled",
                "DEMO-POLICY-001",
            ),
        )

    return database, AuditRepository(database)


def make_audit_event(**overrides):
    data = {
        "case_id": "CASE-001",
        "actor_id": "NURSE-001",
        "action": "recheck.scheduled",
        "entity_id": "RECHECK-001",
        "details": {"policy_reference": "DEMO-POLICY-001"},
    }
    data.update(overrides)
    return AuditEvent(**data)


def test_append_and_retrieve_audit_event(audit_setup):
    _, repository = audit_setup
    event = make_audit_event()

    repository.append(event)

    events = repository.get_for_case("CASE-001")

    assert len(events) == 1
    assert events[0].event_id == event.event_id
    assert events[0].actor_id == "NURSE-001"
    assert events[0].details == {"policy_reference": "DEMO-POLICY-001"}


def test_duplicate_audit_event_is_rejected(audit_setup):
    _, repository = audit_setup
    event = make_audit_event()

    repository.append(event)

    with pytest.raises(ValueError, match="could not be saved"):
        repository.append(event)


def test_audit_events_cannot_be_updated(audit_setup):
    database, repository = audit_setup
    event = make_audit_event()
    repository.append(event)

    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
        connection.execute(
            """
                UPDATE audit_events
                SET actor_id = ?
                WHERE event_id = ?
                """,
            ("NURSE-999", event.event_id),
        )


def test_audit_events_cannot_be_deleted(audit_setup):
    database, repository = audit_setup
    event = make_audit_event()
    repository.append(event)

    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
        connection.execute(
            """
                DELETE FROM audit_events
                WHERE event_id = ?
                """,
            (event.event_id,),
        )


def test_audit_history_survives_repository_restart(audit_setup):
    database, repository = audit_setup
    event = make_audit_event()
    repository.append(event)

    restarted_repository = AuditRepository(Database(database.database_path))

    events = restarted_repository.get_for_case("CASE-001")

    assert len(events) == 1
    assert events[0].event_id == event.event_id


def test_audit_event_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone"):
        make_audit_event(occurred_at=datetime(2026, 10, 14, 9, 0))


def test_audit_event_rejects_unsupported_action():
    with pytest.raises(ValueError):
        make_audit_event(action="priority.changed")
