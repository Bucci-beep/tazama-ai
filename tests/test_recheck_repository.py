from datetime import UTC, datetime, timedelta

import pytest

from tazama.mcp.contracts import PatientObservations
from tazama.patients.models import ObservationRecord
from tazama.patients.reassessment import RecheckObligation
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.rechecks import RecheckRepository


@pytest.fixture
def repositories(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    return ObservationRepository(database), RecheckRepository(database)


def make_baseline():
    return ObservationRecord(
        case_id="JOSEPH-001",
        observation_type="baseline",
        recorded_at=datetime.now(UTC) - timedelta(minutes=10),
        observations=PatientObservations(
            respiratory_rate_bpm=18.0,
            spo2_percent=98.0,
        ),
    )


def make_obligation():
    return RecheckObligation(
        case_id="JOSEPH-001",
        due_at=datetime.now(UTC) + timedelta(minutes=30),
        policy_reference="DEMO-POLICY-001",
    )


def test_schedule_persists_obligation(repositories):
    observations, rechecks = repositories

    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    stored = rechecks.get(obligation.obligation_id)

    assert stored is not None
    assert stored.case_id == "JOSEPH-001"
    assert stored.status == "scheduled"


def test_schedule_requires_baseline(repositories):
    _, rechecks = repositories

    with pytest.raises(ValueError, match="baseline"):
        rechecks.schedule(make_obligation())


def test_duplicate_obligation_id_rejected(repositories):
    observations, rechecks = repositories

    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    with pytest.raises(ValueError):
        rechecks.schedule(obligation)


def test_missing_obligation_returns_none(repositories):
    _, rechecks = repositories

    assert rechecks.get("UNKNOWN-ID") is None


def test_recheck_survives_repository_restart(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    observations = ObservationRepository(database)
    observations.save(make_baseline())

    first_repository = RecheckRepository(database)
    obligation = make_obligation()
    first_repository.schedule(obligation)

    second_repository = RecheckRepository(Database(database.database_path))

    stored = second_repository.get(obligation.obligation_id)

    assert stored is not None
    assert stored.obligation_id == obligation.obligation_id


def test_get_due_returns_overdue_obligation(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    as_of = obligation.due_at + timedelta(minutes=10)
    results = rechecks.get_due(as_of)

    assert len(results) == 1
    assert results[0].obligation_id == obligation.obligation_id


def test_get_due_excludes_future_obligation(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    as_of = obligation.created_at + timedelta(minutes=5)
    results = rechecks.get_due(as_of)

    assert results == []


def test_get_due_includes_exact_due_time(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    results = rechecks.get_due(obligation.due_at)

    assert len(results) == 1


def test_get_due_rejects_naive_datetime(repositories):
    _, rechecks = repositories

    with pytest.raises(ValueError, match="timezone"):
        rechecks.get_due(datetime(2026, 10, 13, 9, 0))


def make_recheck(case_id="JOSEPH-001"):
    return ObservationRecord(
        case_id=case_id,
        observation_type="recheck",
        recorded_at=datetime.now(UTC) + timedelta(minutes=1),
        observations=PatientObservations(
            respiratory_rate_bpm=20.0,
            spo2_percent=97.0,
        ),
    )


def test_complete_reassessment(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    recheck = make_recheck()
    observations.save(recheck)

    completed_at = datetime.now(UTC) + timedelta(minutes=2)
    rechecks.complete(
        obligation.obligation_id,
        recheck.observation_id,
        completed_at,
    )

    with rechecks.database.connect() as connection:
        row = connection.execute(
            """
            SELECT status, completed_observation_id, completed_at
            FROM recheck_obligations
            WHERE obligation_id = ?
            """,
            (obligation.obligation_id,),
        ).fetchone()

    assert row[0] == "completed"
    assert row[1] == recheck.observation_id
    assert row[2] is not None


def test_cannot_complete_with_baseline(repositories):
    observations, rechecks = repositories

    baseline = make_baseline()
    observations.save(baseline)

    obligation = make_obligation()
    rechecks.schedule(obligation)

    with pytest.raises(ValueError, match="recheck"):
        rechecks.complete(
            obligation.obligation_id,
            baseline.observation_id,
            datetime.now(UTC) + timedelta(minutes=2),
        )


def test_cannot_complete_with_other_patient_observation(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    other_baseline = ObservationRecord(
        case_id="GRACE-001",
        observation_type="baseline",
        recorded_at=datetime.now(UTC) - timedelta(minutes=10),
        observations=PatientObservations(
            respiratory_rate_bpm=17.0,
            spo2_percent=99.0,
        ),
    )
    observations.save(other_baseline)

    other_recheck = make_recheck("GRACE-001")
    observations.save(other_recheck)

    with pytest.raises(ValueError, match="different patient"):
        rechecks.complete(
            obligation.obligation_id,
            other_recheck.observation_id,
            datetime.now(UTC) + timedelta(minutes=2),
        )


def test_cannot_complete_twice(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    recheck = make_recheck()
    observations.save(recheck)

    completed_at = datetime.now(UTC) + timedelta(minutes=2)

    rechecks.complete(
        obligation.obligation_id,
        recheck.observation_id,
        completed_at,
    )

    with pytest.raises(ValueError, match="scheduled"):
        rechecks.complete(
            obligation.obligation_id,
            recheck.observation_id,
            completed_at,
        )


def test_cannot_complete_without_observation(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    with pytest.raises(ValueError, match="not found"):
        rechecks.complete(
            obligation.obligation_id,
            "UNKNOWN-OBSERVATION",
            datetime.now(UTC) + timedelta(minutes=2),
        )


def test_cancel_scheduled_reassessment(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    rechecks.cancel(
        obligation_id=obligation.obligation_id,
        reason="Duplicate scheduling entry",
        actor_id="NURSE-001",
        cancelled_at=datetime.now(UTC),
    )

    with rechecks.database.connect() as connection:
        row = connection.execute(
            """
            SELECT status, cancellation_reason, cancelled_at
            FROM recheck_obligations
            WHERE obligation_id = ?
            """,
            (obligation.obligation_id,),
        ).fetchone()

    assert row[0] == "cancelled"
    assert row[1] == "Duplicate scheduling entry"
    assert row[2] is not None


def test_cancel_requires_reason(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    with pytest.raises(ValueError, match="reason"):
        rechecks.cancel(
            obligation.obligation_id,
            "   ",
            "NURSE-001",
            datetime.now(UTC),
        )


def test_cancel_requires_actor(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    with pytest.raises(ValueError, match="Actor"):
        rechecks.cancel(
            obligation.obligation_id,
            "Duplicate entry",
            "",
            datetime.now(UTC),
        )


def test_cannot_cancel_twice(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    cancelled_at = datetime.now(UTC)

    rechecks.cancel(
        obligation.obligation_id,
        "Duplicate entry",
        "NURSE-001",
        cancelled_at,
    )

    with pytest.raises(ValueError, match="scheduled"):
        rechecks.cancel(
            obligation.obligation_id,
            "Another reason",
            "NURSE-001",
            cancelled_at,
        )


def test_cannot_cancel_completed_reassessment(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    recheck = make_recheck()
    observations.save(recheck)

    rechecks.complete(
        obligation.obligation_id,
        recheck.observation_id,
        datetime.now(UTC) + timedelta(minutes=2),
    )

    with pytest.raises(ValueError, match="scheduled"):
        rechecks.cancel(
            obligation.obligation_id,
            "No longer required",
            "NURSE-001",
            datetime.now(UTC) + timedelta(minutes=3),
        )


def test_cancel_rejects_timestamp_before_creation(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    with pytest.raises(ValueError, match="predate"):
        rechecks.cancel(
            obligation.obligation_id,
            "Duplicate entry",
            "NURSE-001",
            obligation.created_at - timedelta(minutes=1),
        )


def test_cancelled_reassessment_excluded_from_due_queue(repositories):
    observations, rechecks = repositories
    observations.save(make_baseline())

    obligation = make_obligation()
    rechecks.schedule(obligation)

    rechecks.cancel(
        obligation.obligation_id,
        "Duplicate entry",
        "NURSE-001",
        datetime.now(UTC),
    )

    due = rechecks.get_due(obligation.due_at + timedelta(minutes=10))

    assert due == []
