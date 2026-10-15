"""FastAPI tests for synthetic reassessment through the existing workflow."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tazama.api.app import app
from tazama.api.dependencies import get_reassessment_service
from tazama.api.reassessment import ReassessmentService
from tazama.clinical.history import CompareHistoryResult
from tazama.clinical.priority import determine_priority
from tazama.mcp.contracts import PatientObservations
from tazama.orchestration.mcp_audit import MCPAuditPersistenceError
from tazama.orchestration.mcp_time import TimeContext
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.mcp_audit import MCPToolCallRepository
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRepository, ReviewRequest

CASE_ID = "SYNTHETIC-REASSESS-1"


@pytest.fixture
def repository(tmp_path):
    database = Database(tmp_path / "reassessment.sqlite3")
    database.initialize()
    return ObservationRepository(database)


def seed(repository: ObservationRepository) -> None:
    start = datetime(2026, 10, 14, 10, tzinfo=UTC)
    for index, observation_type in enumerate(("baseline", "recheck")):
        repository.save(
            ObservationRecord(
                observation_id=f"OBS-{index + 1}",
                case_id=CASE_ID,
                observation_type=observation_type,
                recorded_at=start + timedelta(minutes=index * 10),
                observations=PatientObservations(
                    heart_rate_bpm=float(80 + index * 10),
                    respiratory_rate_bpm=18.0,
                    systolic_bp_mmhg=120.0,
                    temperature_c=37.0,
                    consciousness="alert",
                    mobility="walking",
                    trauma=False,
                ),
            )
        )


async def history(request):
    return CompareHistoryResult(case_id=request.case_id, status="differences_found")


async def priority(request):
    return determine_priority(request.observations, request.signs)


async def review(request):
    return ReviewRequest(
        request_id="REVIEW-API-001",
        case_id=request.case_id,
        observation_id=request.observation_id,
        status="pending",
        created_at=datetime.now(UTC),
        comparison_status=request.comparison_status,
        evidence=request.evidence,
    )


async def time_context():
    return TimeContext(
        timezone="UTC",
        datetime=datetime(2026, 10, 15, 9, tzinfo=UTC),
        day_of_week="Thursday",
        is_dst=False,
    )


def service_for(repository, **overrides) -> ReassessmentService:
    tools = {
        "history_tool": history,
        "priority_tool": priority,
        "review_tool": review,
        "time_tool": time_context,
    }
    tools.update(overrides)
    return ReassessmentService(repository, **tools)


def request_with(service: ReassessmentService, path: str) -> tuple[int, dict]:
    app.dependency_overrides[get_reassessment_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(path)
    finally:
        app.dependency_overrides.clear()
    return response.status_code, response.json()


def test_successful_synthetic_reassessment(repository):
    seed(repository)
    status_code, payload = request_with(
        service_for(repository), f"/api/v1/cases/{CASE_ID}/reassess"
    )

    assert status_code == 200
    assert payload["case_id"] == CASE_ID
    assert payload["workflow_run_id"]
    assert payload["status"] == "awaiting_clinician_review"
    assert payload["observation_count"] == 2
    assert payload["latest_observation_id"] == "OBS-2"
    assert payload["comparison_status"] == "differences_found"
    assert payload["priority_status"] == "minimum_only"
    assert payload["priority_result"]["priority_at_least"] == "routine"
    assert payload["review_submission_status"] == "persisted"
    assert payload["review_request_id"] == "REVIEW-API-001"
    assert payload["mcp_audit_errors"] == []


def test_unknown_case_returns_404_without_review(repository):
    called = False

    async def forbidden_review(request):
        nonlocal called
        called = True
        return await review(request)

    status_code, payload = request_with(
        service_for(repository, review_tool=forbidden_review),
        "/api/v1/cases/UNKNOWN/reassess",
    )
    assert status_code == 404
    assert payload == {"detail": "No observations found for case"}
    assert called is False


def test_database_with_no_observations_returns_404(repository):
    status_code, _ = request_with(
        service_for(repository), f"/api/v1/cases/{CASE_ID}/reassess"
    )
    assert status_code == 404


@pytest.mark.parametrize("case_id", ["%20", "invalid case", "!invalid"])
def test_invalid_case_id_returns_422(repository, case_id):
    status_code, _ = request_with(
        service_for(repository), f"/api/v1/cases/{case_id}/reassess"
    )
    assert status_code == 422


@pytest.mark.parametrize(
    ("tool_name", "expected_status", "expected_error"),
    [
        ("history_tool", "tool_unavailable", "MCP_HISTORY_TOOL_UNAVAILABLE"),
        ("priority_tool", "tool_unavailable", "MCP_PRIORITY_TOOL_UNAVAILABLE"),
    ],
)
def test_clinical_mcp_failure_is_explicit(
    repository, tool_name, expected_status, expected_error
):
    seed(repository)

    async def broken(request):
        raise TimeoutError("synthetic MCP failure")

    status_code, payload = request_with(
        service_for(repository, **{tool_name: broken}),
        f"/api/v1/cases/{CASE_ID}/reassess",
    )
    assert status_code == 200
    field = "comparison" if tool_name == "history_tool" else "priority"
    assert payload[f"{field}_status"] == expected_status
    assert payload[f"{field}_error"] == expected_error
    assert payload["review_submission_status"] == "persisted"


def test_time_mcp_failure_is_nonblocking_and_explicit(repository):
    seed(repository)

    async def broken_time():
        raise TimeoutError("synthetic Time MCP failure")

    status_code, payload = request_with(
        service_for(repository, time_tool=broken_time),
        f"/api/v1/cases/{CASE_ID}/reassess",
    )
    assert status_code == 200
    assert payload["workflow_provenance"]["time"]["status"] == "tool_unavailable"
    assert payload["priority_status"] == "minimum_only"


def test_ollama_unavailable_is_explicit_and_nonblocking(repository):
    seed(repository)
    status_code, payload = request_with(
        service_for(repository, explanation_tool=None),
        f"/api/v1/cases/{CASE_ID}/reassess",
    )
    assert status_code == 200
    assert payload["explanation"] is None
    assert payload["explanation_error"] == "NOT_CONFIGURED"
    assert payload["review_submission_status"] == "persisted"


def test_review_submission_unconfirmed_is_preserved(repository):
    seed(repository)

    async def broken_review(request):
        raise TimeoutError("synthetic review transport failure")

    status_code, payload = request_with(
        service_for(repository, review_tool=broken_review),
        f"/api/v1/cases/{CASE_ID}/reassess",
    )
    assert status_code == 200
    assert payload["status"] == "review_submission_failed"
    assert payload["review_submission_status"] == "unconfirmed"
    assert payload["review_request_id"] is None


def test_audit_failure_preserves_successful_mcp_result(repository):
    seed(repository)

    async def time_with_audit_failure():
        raise MCPAuditPersistenceError(await time_context())

    status_code, payload = request_with(
        service_for(repository, time_tool=time_with_audit_failure),
        f"/api/v1/cases/{CASE_ID}/reassess",
    )
    assert status_code == 200
    assert payload["workflow_provenance"]["time"]["status"] == "captured"
    assert (
        payload["workflow_provenance"]["time"]["audit_status"] == "persistence_failed"
    )
    assert payload["mcp_audit_errors"] == [
        "get_current_time:MCP_AUDIT_PERSISTENCE_FAILED"
    ]


def test_real_mcp_workflow_is_idempotent_and_audited(repository):
    seed(repository)
    service = ReassessmentService(repository)

    first_status, first = request_with(service, f"/api/v1/cases/{CASE_ID}/reassess")
    second_status, second = request_with(service, f"/api/v1/cases/{CASE_ID}/reassess")

    assert first_status == second_status == 200
    assert first["review_request_id"] == second["review_request_id"]
    assert len(ReviewRepository(repository.database).get_pending()) == 1
    assert (
        len(
            MCPToolCallRepository(repository.database).get_by_workflow_run(
                first["workflow_run_id"]
            )
        )
        == 4
    )


@pytest.mark.parametrize(
    ("body", "expected_status", "expected_priority", "expected_assessed"),
    [
        (None, "minimum_only", None, False),
        ({"signs": None}, "minimum_only", None, False),
        ({"signs": []}, "complete", "routine", True),
    ],
    ids=["omitted", "explicit-null", "assessed-none-found"],
)
def test_reassessment_sign_assessment_contract(
    repository,
    body,
    expected_status,
    expected_priority,
    expected_assessed,
):
    """Preserve the distinction between unassessed and assessed signs."""
    seed(repository)
    submitted = []

    async def capture_review(request):
        submitted.append(request)
        return await review(request)

    service = service_for(repository, review_tool=capture_review)

    app.dependency_overrides[get_reassessment_service] = lambda: service
    try:
        with TestClient(app) as client:
            if body is None:
                response = client.post(f"/api/v1/cases/{CASE_ID}/reassess")
            else:
                response = client.post(
                    f"/api/v1/cases/{CASE_ID}/reassess",
                    json=body,
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text

    result = response.json()
    assert result["priority_status"] == expected_status

    priority_result = result["priority_result"]
    assert priority_result is not None
    assert priority_result["priority"] == expected_priority

    if expected_status == "minimum_only":
        assert priority_result["priority_at_least"] == "routine"
    else:
        assert priority_result["priority_at_least"] is None

    assert result["review_submission_status"] == "persisted"
    assert len(submitted) == 1
    assert submitted[0].evidence["signs_assessed"] is expected_assessed
    assert submitted[0].evidence["priority_result"] == priority_result


@pytest.mark.parametrize(
    ("signs", "expected_status", "expected_priority", "expected_evidence_key"),
    [
        (
            ["DISC/URGENT/MODERATE_PAIN"],
            "complete",
            "urgent",
            "matched_sign_ids",
        ),
        (["DISC/NOT/A_REAL_SIGN"], "abstained", None, "unknown_sign_ids"),
    ],
    ids=["recognised", "unknown"],
)
def test_reassessment_preserves_submitted_sign_ids(
    repository,
    signs,
    expected_status,
    expected_priority,
    expected_evidence_key,
):
    seed(repository)
    submitted = []

    async def capture_review(request):
        submitted.append(request)
        return await review(request)

    service = service_for(repository, review_tool=capture_review)
    app.dependency_overrides[get_reassessment_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/cases/{CASE_ID}/reassess",
                json={"signs": signs},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["priority_status"] == expected_status
    assert result["priority_result"]["priority"] == expected_priority
    assert result["priority_result"][expected_evidence_key] == signs
    assert submitted[0].evidence["signs_assessed"] is True
    assert submitted[0].evidence["priority_result"] == result["priority_result"]


def test_changed_sign_assessment_for_same_observation_fails_closed(repository):
    """Never reuse a pending review whose deterministic evidence has changed."""
    seed(repository)
    reviews = ReviewRepository(repository.database)
    reviews.initialize()

    async def persist_review(request):
        return reviews.submit(request)

    service = service_for(repository, review_tool=persist_review)
    app.dependency_overrides[get_reassessment_service] = lambda: service
    try:
        with TestClient(app) as client:
            first = client.post(f"/api/v1/cases/{CASE_ID}/reassess")
            second = client.post(
                f"/api/v1/cases/{CASE_ID}/reassess",
                json={"signs": []},
            )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    assert first.json()["review_submission_status"] == "persisted"
    assert second.json()["priority_status"] == "complete"
    assert second.json()["review_submission_status"] == "unconfirmed"
    assert second.json()["review_request_id"] is None
    assert second.json()["review_submission_error"] == (
        "MCP_REVIEW_SUBMISSION_UNCONFIRMED"
    )

    pending = reviews.get_pending()
    assert len(pending) == 1
    assert pending[0].request_id == first.json()["review_request_id"]
    assert pending[0].evidence["signs_assessed"] is False
    with repository.database.connect() as connection:
        event_count = connection.execute(
            "SELECT COUNT(*) FROM review_request_events"
        ).fetchone()[0]
    assert event_count == 1


@pytest.mark.parametrize(
    "body",
    [
        {"signs": "invalid"},
        {"signs": [123]},
        {"signs": {"id": "invalid"}},
        {"signs": [], "unexpected": True},
    ],
)
def test_reassessment_rejects_malformed_signs(repository, body):
    """Reject malformed requests before invoking the clinical workflow."""
    seed(repository)

    app.dependency_overrides[get_reassessment_service] = lambda: service_for(repository)

    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/cases/{CASE_ID}/reassess",
                json=body,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422, response.text
