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
    assert payload["workflow_provenance"]["time"]["audit_status"] == "persistence_failed"
    assert payload["mcp_audit_errors"] == [
        "get_current_time:MCP_AUDIT_PERSISTENCE_FAILED"
    ]


def test_real_mcp_workflow_is_idempotent_and_audited(repository):
    seed(repository)
    service = ReassessmentService(repository)

    first_status, first = request_with(
        service, f"/api/v1/cases/{CASE_ID}/reassess"
    )
    second_status, second = request_with(
        service, f"/api/v1/cases/{CASE_ID}/reassess"
    )

    assert first_status == second_status == 200
    assert first["review_request_id"] == second["review_request_id"]
    assert len(ReviewRepository(repository.database).get_pending()) == 1
    assert len(
        MCPToolCallRepository(repository.database).get_by_workflow_run(
            first["workflow_run_id"]
        )
    ) == 4
