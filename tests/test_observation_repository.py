from datetime import UTC, datetime, timedelta

import pytest

from tazama.mcp.contracts import PatientObservations
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository

BASE_TIME = datetime(2026, 10, 13, 8, 15, tzinfo=UTC)


def make_record(
    minutes: int,
    observation_type: str,
    case_id: str = "JOSEPH-001",
) -> ObservationRecord:
    return ObservationRecord(
        case_id=case_id,
        observation_type=observation_type,
        recorded_at=BASE_TIME + timedelta(minutes=minutes),
        observations=PatientObservations(
            respiratory_rate_bpm=18.0,
            spo2_percent=98.0,
        ),
    )


@pytest.fixture
def repository(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()
    return ObservationRepository(database)


def test_baseline_persists(repository):
    baseline = make_record(0, "baseline")
    repository.save(baseline)

    timeline = repository.get_timeline("JOSEPH-001")

    assert len(timeline.records) == 1
    assert timeline.records[0].observation_id == baseline.observation_id


def test_recheck_persists(repository):
    repository.save(make_record(0, "baseline"))
    repository.save(make_record(30, "recheck"))

    timeline = repository.get_timeline("JOSEPH-001")

    assert len(timeline.records) == 2
    assert timeline.latest().observation_type == "recheck"


def test_recheck_without_baseline_rejected(repository):
    with pytest.raises(ValueError):
        repository.save(make_record(30, "recheck"))


def test_out_of_order_recheck_rejected(repository):
    repository.save(make_record(0, "baseline"))
    repository.save(make_record(30, "recheck"))

    with pytest.raises(ValueError):
        repository.save(make_record(15, "recheck"))


def test_duplicate_observation_rejected(repository):
    baseline = make_record(0, "baseline")
    repository.save(baseline)

    with pytest.raises(ValueError):
        repository.save(baseline)


def test_patient_histories_are_isolated(repository):
    repository.save(make_record(0, "baseline", "JOSEPH-001"))
    repository.save(make_record(0, "baseline", "GRACE-001"))

    joseph = repository.get_timeline("JOSEPH-001")
    grace = repository.get_timeline("GRACE-001")

    assert len(joseph.records) == 1
    assert len(grace.records) == 1
    assert joseph.records[0].case_id != grace.records[0].case_id


def test_observations_survive_new_repository_instance(tmp_path):
    database = Database(tmp_path / "tazama.db")
    database.initialize()

    first_repository = ObservationRepository(database)
    baseline = make_record(0, "baseline")
    first_repository.save(baseline)

    second_repository = ObservationRepository(Database(database.database_path))
    timeline = second_repository.get_timeline("JOSEPH-001")

    assert timeline.records[0].observation_id == baseline.observation_id
