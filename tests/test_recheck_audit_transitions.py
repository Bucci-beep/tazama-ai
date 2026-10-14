"""Audit integration tests for reassessment state transitions."""

from datetime import UTC, datetime, timedelta

import pytest

from tazama.storage.audit import AuditRepository
from tazama.storage.database import Database
from tazama.storage.rechecks import RecheckRepository


@pytest.fixture
def workflow(tmp_path):
    db = Database(tmp_path / "transitions.db")
    db.initialize()

    now = datetime.now(UTC)
    created = now - timedelta(minutes=10)
    recorded = now - timedelta(minutes=5)

    with db.connect() as connection:
        connection.execute(
            """
            INSERT INTO observations (
                observation_id, case_id, observation_type,
                recorded_at, received_at, observations_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "BASE-001",
                "CASE-001",
                "baseline",
                created.isoformat(),
                created.isoformat(),
                "{}",
            ),
        )
        connection.execute(
            """
            INSERT INTO observations (
                observation_id, case_id, observation_type,
                recorded_at, received_at, observations_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "RECHECK-OBS-001",
                "CASE-001",
                "recheck",
                recorded.isoformat(),
                recorded.isoformat(),
                "{}",
            ),
        )

        for obligation_id in ("OBL-001", "OBL-002"):
            connection.execute(
                """
                INSERT INTO recheck_obligations (
                    obligation_id, case_id, due_at,
                    created_at, status, policy_reference
                ) VALUES (?, ?, ?, ?, 'scheduled', ?)
                """,
                (
                    obligation_id,
                    "CASE-001",
                    (now + timedelta(minutes=20)).isoformat(),
                    created.isoformat(),
                    "DEMO-POLICY-001",
                ),
            )

    return db, RecheckRepository(db), AuditRepository(db)


def get_state(db, obligation_id):
    with db.connect() as connection:
        return connection.execute(
            """
            SELECT status FROM recheck_obligations
            WHERE obligation_id = ?
            """,
            (obligation_id,),
        ).fetchone()[0]


def reject_audit_inserts(db):
    with db.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_transition_audit
            BEFORE INSERT ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Simulated audit failure');
            END
            """
        )


def test_completion_creates_audit_event(workflow):
    db, rechecks, audit = workflow

    rechecks.complete(
        "OBL-001",
        "RECHECK-OBS-001",
        datetime.now(UTC),
        actor_id="NURSE-001",
    )

    events = audit.get_for_case("CASE-001")

    assert get_state(db, "OBL-001") == "completed"
    assert len(events) == 1
    assert events[0].action == "recheck.completed"
    assert events[0].actor_id == "NURSE-001"
    assert events[0].entity_id == "OBL-001"
    assert events[0].details == {"observation_id": "RECHECK-OBS-001"}


def test_cancellation_creates_audit_event(workflow):
    db, rechecks, audit = workflow

    rechecks.cancel(
        "OBL-002",
        "Duplicate scheduling entry",
        "NURSE-002",
        datetime.now(UTC),
    )

    events = audit.get_for_case("CASE-001")

    assert get_state(db, "OBL-002") == "cancelled"
    assert len(events) == 1
    assert events[0].action == "recheck.cancelled"
    assert events[0].actor_id == "NURSE-002"
    assert events[0].entity_id == "OBL-002"
    assert events[0].details["reason"] == "Duplicate scheduling entry"


def test_completion_rolls_back_if_audit_fails(workflow):
    db, rechecks, audit = workflow
    reject_audit_inserts(db)

    with pytest.raises(ValueError, match="audit persistence failed"):
        rechecks.complete(
            "OBL-001",
            "RECHECK-OBS-001",
            datetime.now(UTC),
            actor_id="NURSE-001",
        )

    assert get_state(db, "OBL-001") == "scheduled"
    assert audit.get_for_case("CASE-001") == []


def test_cancellation_rolls_back_if_audit_fails(workflow):
    db, rechecks, audit = workflow
    reject_audit_inserts(db)

    with pytest.raises(ValueError, match="audit persistence failed"):
        rechecks.cancel(
            "OBL-002",
            "Duplicate entry",
            "NURSE-001",
            datetime.now(UTC),
        )

    assert get_state(db, "OBL-002") == "scheduled"
    assert audit.get_for_case("CASE-001") == []


def test_both_transitions_have_readable_audit_events(workflow):
    _, rechecks, audit = workflow

    rechecks.complete(
        "OBL-001",
        "RECHECK-OBS-001",
        datetime.now(UTC),
        actor_id="NURSE-001",
    )
    rechecks.cancel(
        "OBL-002",
        "Duplicate entry",
        "NURSE-002",
        datetime.now(UTC),
    )

    events = audit.get_for_case("CASE-001")

    assert len(events) == 2
    assert {event.action for event in events} == {
        "recheck.completed",
        "recheck.cancelled",
    }
    assert all(isinstance(event.details, dict) for event in events)
