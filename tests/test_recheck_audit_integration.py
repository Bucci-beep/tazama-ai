"""Atomic audit integration tests for reassessment scheduling."""

from datetime import UTC, datetime, timedelta

import pytest

from tazama.patients.reassessment import RecheckObligation
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.rechecks import RecheckRepository


@pytest.fixture
def setup(tmp_path):
    database = Database(tmp_path / "integration.db")
    database.initialize()

    observations = ObservationRepository(database)
    rechecks = RecheckRepository(database)

    return database, observations, rechecks


def create_baseline(database, case_id="CASE-001"):
    now = datetime.now(UTC)

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
                f"BASELINE-{case_id}",
                case_id,
                "baseline",
                now.isoformat(),
                now.isoformat(),
                "{}",
            ),
        )


def make_obligation(case_id="CASE-001"):
    now = datetime.now(UTC)

    return RecheckObligation(
        case_id=case_id,
        created_at=now,
        due_at=now + timedelta(minutes=30),
        policy_reference="DEMO-POLICY-001",
    )


def test_scheduling_creates_audit_event(setup):
    database, _, rechecks = setup
    create_baseline(database)

    obligation = make_obligation()

    rechecks.schedule(
        obligation,
        actor_id="NURSE-001",
    )

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT case_id, actor_id, action, entity_id
            FROM audit_events
            WHERE entity_id = ?
            """,
            (obligation.obligation_id,),
        ).fetchone()

    assert row == (
        "CASE-001",
        "NURSE-001",
        "recheck.scheduled",
        obligation.obligation_id,
    )


def test_scheduling_rolls_back_if_audit_insert_fails(setup):
    database, _, rechecks = setup
    create_baseline(database)

    obligation = make_obligation()

    with database.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_scheduling_audit
            BEFORE INSERT ON audit_events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Simulated audit persistence failure'
                );
            END
            """
        )

    with pytest.raises(ValueError, match="audit persistence failed"):
        rechecks.schedule(
            obligation,
            actor_id="NURSE-001",
        )

    with database.connect() as connection:
        obligation_row = connection.execute(
            """
            SELECT obligation_id
            FROM recheck_obligations
            WHERE obligation_id = ?
            """,
            (obligation.obligation_id,),
        ).fetchone()

        audit_row = connection.execute(
            """
            SELECT event_id
            FROM audit_events
            WHERE entity_id = ?
            """,
            (obligation.obligation_id,),
        ).fetchone()

    assert obligation_row is None
    assert audit_row is None


def test_scheduling_rejects_blank_actor(setup):
    database, _, rechecks = setup
    create_baseline(database)

    with pytest.raises(ValueError, match="Actor ID"):
        rechecks.schedule(
            make_obligation(),
            actor_id="   ",
        )
