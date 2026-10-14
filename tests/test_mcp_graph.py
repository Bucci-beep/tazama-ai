"""LangGraph-to-MCP workflow tests using synthetic patient data."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from tazama.clinical.history import CompareHistoryResult
from tazama.mcp.contracts import PatientObservations
from tazama.orchestration.mcp_graph import build_mcp_triage_graph
from tazama.patients.models import ObservationRecord, PatientTimeline
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRepository, ReviewRequest


def make_timeline(count: int) -> PatientTimeline:
    timeline = PatientTimeline(case_id="CASE-MCP-001")

    for index in range(count):
        timeline.add_record(
            ObservationRecord(
                observation_id=f"OBS-{index + 1}",
                case_id="CASE-MCP-001",
                recorded_at=datetime(2026, 10, 14, 8, tzinfo=UTC)
                + timedelta(minutes=index * 10),
                observation_type="baseline" if index == 0 else "recheck",
                observations=PatientObservations(
                    heart_rate_bpm=float(80 + index * 10),
                    respiratory_rate_bpm=12.0,
                    systolic_bp_mmhg=120.0,
                    temperature_c=37.0,
                    consciousness="alert",
                    mobility="walking",
                    trauma=False,
                ),
            )
        )

    return timeline


def repository_for(count: int):
    repo = Mock()
    repo.get_timeline.return_value = make_timeline(count)
    return repo


def initial_state(case_id="CASE-MCP-001"):
    return {"case_id": case_id, "status": "pending", "reason": None}


async def fake_history(request):
    return CompareHistoryResult(
        case_id=request.case_id,
        status="differences_found",
    )


async def fake_review(request):
    return ReviewRequest(
        request_id="REVIEW-001",
        case_id=request.case_id,
        observation_id=request.observation_id,
        status="pending",
        created_at=datetime.now(UTC),
        comparison_status=request.comparison_status,
        evidence=request.evidence,
    )


@pytest.mark.asyncio
async def test_comparison_uses_latest_two_observations():
    received = []

    async def history(request):
        received.append(request)
        return await fake_history(request)

    graph = build_mcp_triage_graph(repository_for(3), history, fake_review)
    result = await graph.ainvoke(initial_state())

    assert received[0].before.obs_id == "OBS-2"
    assert received[0].after.obs_id == "OBS-3"
    assert result["comparison_status"] == "differences_found"
    assert result["review_request_id"] == "REVIEW-001"
    assert result["review_submission_status"] == "persisted"
    assert result["status"] == "awaiting_clinician_review"


@pytest.mark.asyncio
async def test_empty_timeline_never_submits_review():
    async def forbidden(request):
        raise AssertionError("No MCP call should occur")

    graph = build_mcp_triage_graph(repository_for(0), forbidden, forbidden)
    result = await graph.ainvoke(initial_state())

    assert result["comparison_status"] == "insufficient_history"
    assert result["status"] == "observation_missing"
    assert result["review_submission_status"] == "not_attempted"
    assert result["review_request_id"] is None


@pytest.mark.asyncio
async def test_history_failure_still_requests_review():
    async def broken_history(request):
        raise RuntimeError("History MCP unavailable")

    received = []

    async def review(request):
        received.append(request)
        return await fake_review(request)

    graph = build_mcp_triage_graph(repository_for(2), broken_history, review)
    result = await graph.ainvoke(initial_state())

    assert result["comparison_status"] == "tool_unavailable"
    assert result["comparison_result"] is None
    assert received[0].comparison_status == "tool_unavailable"
    assert result["review_submission_status"] == "persisted"
    assert result["status"] == "awaiting_clinician_review"
    assert result["reason"] == "HISTORY_COMPARISON_UNAVAILABLE"


@pytest.mark.asyncio
async def test_priority_failure_is_persisted_as_unavailable_not_negative():
    async def broken_priority(request):
        raise RuntimeError("Priority MCP unavailable")

    received = []

    async def review(request):
        received.append(request)
        return await fake_review(request)

    graph = build_mcp_triage_graph(
        repository_for(2), fake_history, review, broken_priority
    )
    result = await graph.ainvoke(initial_state())

    assert result["priority_status"] == "tool_unavailable"
    assert result["priority_result"] is None
    assert received[0].evidence["priority_error"] == "MCP_PRIORITY_TOOL_UNAVAILABLE"
    assert result["status"] == "awaiting_clinician_review"


@pytest.mark.asyncio
async def test_invalid_case_never_queries_repository_or_mcp():
    repository = repository_for(2)

    async def forbidden(request):
        raise AssertionError("MCP must not be called")

    graph = build_mcp_triage_graph(repository, forbidden, forbidden)
    result = await graph.ainvoke(initial_state("  "))

    repository.get_timeline.assert_not_called()
    assert result["status"] == "invalid_input"
    assert result["review_submission_status"] == "not_attempted"


@pytest.mark.asyncio
async def test_mismatched_history_case_is_not_reassuring():
    async def wrong_history(request):
        return CompareHistoryResult(
            case_id="DIFFERENT-CASE",
            status="no_differences",
        )

    graph = build_mcp_triage_graph(repository_for(2), wrong_history, fake_review)
    result = await graph.ainvoke(initial_state())

    assert result["comparison_status"] == "tool_unavailable"
    assert result["comparison_result"] is None
    assert result["comparison_error"] == "MCP_HISTORY_CASE_MISMATCH"
    assert result["status"] == "awaiting_clinician_review"


@pytest.mark.asyncio
async def test_review_submission_failure_is_not_reported_as_queued():
    async def broken_review(request):
        raise RuntimeError("MCP connection lost")

    graph = build_mcp_triage_graph(repository_for(2), fake_history, broken_review)
    result = await graph.ainvoke(initial_state())

    assert result["status"] == "review_submission_failed"
    assert result["review_submission_status"] == "unconfirmed"
    assert result["review_request_id"] is None
    assert result["reason"] == "MCP_REVIEW_SUBMISSION_UNCONFIRMED"


@pytest.mark.asyncio
async def test_mismatched_review_response_fails_closed():
    async def wrong_review(request):
        return ReviewRequest(
            request_id="WRONG-REVIEW",
            case_id="DIFFERENT-CASE",
            observation_id=request.observation_id,
            status="pending",
            created_at=datetime.now(UTC),
            comparison_status=request.comparison_status,
            evidence=request.evidence,
        )

    graph = build_mcp_triage_graph(repository_for(2), fake_history, wrong_review)
    result = await graph.ainvoke(initial_state())

    assert result["status"] == "review_submission_failed"
    assert result["review_request_id"] is None


@pytest.mark.asyncio
async def test_real_mcp_history_and_review_submission(tmp_path):
    """Exercise both real MCP tools and persistent SQLite storage."""
    database = Database(tmp_path / "workflow.sqlite3")
    database.initialize()

    repository = ObservationRepository(database)
    for record in make_timeline(2).records:
        repository.save(record)

    graph = build_mcp_triage_graph(repository)

    first = await graph.ainvoke(initial_state())
    second = await graph.ainvoke(initial_state())

    assert first["comparison_status"] == "differences_found"
    assert first["comparison_error"] is None
    assert first["priority_status"] == "minimum_only"
    assert first["priority_result"]["priority"] is None
    assert first["priority_result"]["priority_at_least"] == "routine"
    assert first["status"] == "awaiting_clinician_review"
    assert first["review_submission_status"] == "persisted"
    assert first["review_request_id"] == second["review_request_id"]

    reviews = ReviewRepository(database).get_pending()
    assert len(reviews) == 1
    assert reviews[0].observation_id == "OBS-2"

    with database.connect() as connection:
        event_count = connection.execute(
            "SELECT COUNT(*) FROM review_request_events"
        ).fetchone()[0]

    assert event_count == 1
