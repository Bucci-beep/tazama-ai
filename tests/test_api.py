"""Integration tests for the read-only synthetic observation API."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tazama.api.app import app
from tazama.api.dependencies import get_observation_repository
from tazama.mcp.contracts import PatientObservations
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository


@pytest.fixture
def repository(tmp_path):
    database = Database(tmp_path / "api.sqlite3")
    database.initialize()
    return ObservationRepository(database)


@pytest.fixture
def client(repository):
    app.dependency_overrides[get_observation_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def observation(
    observation_id: str,
    observation_type: str,
    recorded_at: datetime,
    *,
    heart_rate: float,
) -> ObservationRecord:
    return ObservationRecord(
        observation_id=observation_id,
        case_id="SYNTHETIC-API-1",
        observation_type=observation_type,
        recorded_at=recorded_at,
        observations=PatientObservations(
            heart_rate_bpm=heart_rate,
            spo2_percent=98.0,
            consciousness="alert",
        ),
    )


def test_health_contract_is_unchanged(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "tazama-api",
        "environment": "synthetic-research",
        "clinical_use_permitted": False,
    }


def test_get_one_persisted_baseline_preserves_values(client, repository):
    recorded_at = datetime(2026, 10, 14, 10, tzinfo=UTC)
    repository.save(observation("OBS-1", "baseline", recorded_at, heart_rate=80.0))

    response = client.get("/api/v1/cases/SYNTHETIC-API-1/observations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == "SYNTHETIC-API-1"
    assert payload["records"][0]["observation_id"] == "OBS-1"
    assert payload["records"][0]["recorded_at"] == "2026-10-14T10:00:00Z"
    assert payload["records"][0]["observations"]["heart_rate_bpm"] == 80.0
    assert payload["records"][0]["observations"]["spo2_percent"] == 98.0


def test_get_multiple_observations_is_chronological(client, repository):
    start = datetime(2026, 10, 14, 10, tzinfo=UTC)
    repository.save(observation("OBS-1", "baseline", start, heart_rate=80.0))
    repository.save(
        observation("OBS-2", "recheck", start + timedelta(minutes=5), heart_rate=85.0)
    )
    repository.save(
        observation("OBS-3", "recheck", start + timedelta(minutes=10), heart_rate=90.0)
    )

    response = client.get("/api/v1/cases/SYNTHETIC-API-1/observations")

    assert response.status_code == 200
    assert [record["observation_id"] for record in response.json()["records"]] == [
        "OBS-1",
        "OBS-2",
        "OBS-3",
    ]


def test_unknown_case_returns_consistent_404(client):
    response = client.get("/api/v1/cases/UNKNOWN/observations")

    assert response.status_code == 404
    assert response.json() == {"detail": "No observations found for case"}


def test_missing_database_configuration(monkeypatch):
    monkeypatch.delenv("TAZAMA_DB_PATH", raising=False)
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/cases/CASE-1/observations")

    assert response.status_code == 503
    assert response.json() == {"detail": "TAZAMA_DB_PATH is not configured"}


def test_configured_database_must_exist(monkeypatch, tmp_path):
    missing = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("TAZAMA_DB_PATH", str(missing))
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/cases/CASE-1/observations")

    assert response.status_code == 503
    assert not missing.exists()


def test_malformed_database_returns_503(monkeypatch, tmp_path):
    malformed = tmp_path / "malformed.sqlite3"
    malformed.write_text("not sqlite", encoding="utf-8")
    monkeypatch.setenv("TAZAMA_DB_PATH", str(malformed))
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/cases/CASE-1/observations")

    assert response.status_code == 503


def test_repeated_gets_do_not_modify_database(client, repository):
    repository.save(
        observation(
            "OBS-1",
            "baseline",
            datetime(2026, 10, 14, 10, tzinfo=UTC),
            heart_rate=80.0,
        )
    )
    path = repository.database.database_path
    before = path.read_bytes()

    assert client.get("/api/v1/cases/SYNTHETIC-API-1/observations").status_code == 200
    assert client.get("/api/v1/cases/SYNTHETIC-API-1/observations").status_code == 200

    assert path.read_bytes() == before


def test_retrieval_does_not_call_clinical_or_workflow_code(
    client, repository, monkeypatch
):
    repository.save(
        observation(
            "OBS-1",
            "baseline",
            datetime(2026, 10, 14, 10, tzinfo=UTC),
            heart_rate=80.0,
        )
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Clinical scoring must not run during GET")

    monkeypatch.setattr("tazama.clinical.priority.determine_priority", forbidden)
    monkeypatch.setattr("tazama.clinical.scoring.calculate_sats", forbidden)

    response = client.get("/api/v1/cases/SYNTHETIC-API-1/observations")
    assert response.status_code == 200
