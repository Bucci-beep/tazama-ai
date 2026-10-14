"""Tests for the local research HTTP API."""

from fastapi.testclient import TestClient

from tazama.api.app import app


def test_health_returns_explicit_research_status():
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "tazama-api",
        "environment": "synthetic-research",
        "clinical_use_permitted": False,
    }


def test_health_rejects_unsupported_methods():
    client = TestClient(app)

    response = client.post("/api/v1/health")

    assert response.status_code == 405


def test_no_clinician_approval_endpoint():
    client = TestClient(app)

    response = client.post("/api/v1/reviews/approve")

    assert response.status_code == 404
