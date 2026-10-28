"""LangGraph-to-MCP workflow tests using synthetic patient data."""

import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from tazama.clinical.history import CompareHistoryResult
from tazama.clinical.priority import determine_priority
from tazama.mcp.contracts import PatientObservations
from tazama.orchestration.mcp_graph import build_mcp_triage_graph
from tazama.orchestration.mcp_time import TimeContext
from tazama.patients.models import ObservationRecord, PatientTimeline
from tazama.storage.database import Database
from tazama.storage.mcp_audit import MCPToolCallRepository
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


async def fake_time():
    return TimeContext(
        timezone="UTC",
        datetime=datetime(2026, 10, 15, 6, 30, tzinfo=UTC),
        day_of_week="Thursday",
        is_dst=False,
    )


@pytest.mark.asyncio
async def test_comparison_uses_latest_two_observations():
    received = []

    async def history(request):
        received.append(request)
        return await fake_history(request)

    graph = build_mcp_triage_graph(
        repository_for(3), history, fake_review, time_tool=fake_time
    )
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

    graph = build_mcp_triage_graph(
        repository_for(0), forbidden, forbidden, time_tool=fake_time
    )
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

    graph = build_mcp_triage_graph(
        repository_for(2), broken_history, review, time_tool=fake_time
    )
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
        repository_for(2), fake_history, review, broken_priority, time_tool=fake_time
    )
    result = await graph.ainvoke(initial_state())

    assert result["priority_status"] == "tool_unavailable"
    assert result["priority_result"] is None
    assert received[0].evidence["priority_error"] == "MCP_PRIORITY_TOOL_UNAVAILABLE"
    assert result["status"] == "awaiting_clinician_review"


@pytest.mark.asyncio
async def test_bounded_explanation_is_in_persisted_review_evidence():
    received = []

    async def review(request):
        received.append(request)
        return await fake_review(request)

    async def explain(evidence):
        return {
            "status": "generated",
            "model": "test-model",
            "selected_explanation_ids": ["human_review_required"],
            "statements": ["The evidence requires clinician review."],
        }

    graph = build_mcp_triage_graph(
        repository_for(2),
        fake_history,
        review,
        explanation_tool=explain,
        time_tool=fake_time,
    )
    result = await graph.ainvoke(initial_state())

    assert result["status"] == "awaiting_clinician_review"
    assert received[0].evidence["explanation"]["model"] == "test-model"
    assert received[0].evidence["explanation"]["selected_explanation_ids"] == [
        "human_review_required"
    ]


@pytest.mark.asyncio
async def test_time_mcp_provenance_is_persisted_without_affecting_priority():
    received_reviews = []
    received_priorities = []

    async def review(request):
        received_reviews.append(request)
        return await fake_review(request)

    async def priority(request):
        received_priorities.append(request)
        from tazama.clinical.priority import determine_priority

        return determine_priority(request.observations, request.signs)

    graph = build_mcp_triage_graph(
        repository_for(2),
        fake_history,
        review,
        priority,
        time_tool=fake_time,
    )
    result = await graph.ainvoke(initial_state())

    provenance = received_reviews[0].evidence["workflow_provenance"]["time"]
    assert provenance == {
        "status": "captured",
        "server": "mcp-server-time",
        "tool": "get_current_time",
        "result": {
            "timezone": "UTC",
            "datetime": "2026-10-15T06:30:00Z",
            "day_of_week": "Thursday",
            "is_dst": False,
        },
    }
    assert received_priorities[0].case_id == "CASE-MCP-001"
    assert result["priority_status"] == "minimum_only"
    assert result["status"] == "awaiting_clinician_review"


@pytest.mark.asyncio
async def test_time_mcp_failure_is_explicit_and_nonblocking():
    async def broken_time():
        raise TimeoutError("Time MCP did not respond")

    received = []

    async def review(request):
        received.append(request)
        return await fake_review(request)

    async def priority(request):
        return determine_priority(request.observations, request.signs)

    graph = build_mcp_triage_graph(
        repository_for(2),
        fake_history,
        review,
        priority_tool=priority,
        time_tool=broken_time,
    )
    result = await graph.ainvoke(initial_state())

    assert received[0].evidence["workflow_provenance"] == {
        "time": {
            "status": "tool_unavailable",
            "server": "mcp-server-time",
            "tool": "get_current_time",
            "error": "MCP_TIME_TOOL_UNAVAILABLE",
        }
    }
    assert result["priority_status"] == "minimum_only"
    assert result["review_submission_status"] == "persisted"
    assert result["status"] == "awaiting_clinician_review"


@pytest.mark.asyncio
async def test_invalid_case_never_queries_repository_or_mcp():
    repository = repository_for(2)

    async def forbidden(request):
        raise AssertionError("MCP must not be called")

    graph = build_mcp_triage_graph(
        repository, forbidden, forbidden, time_tool=forbidden
    )
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

    graph = build_mcp_triage_graph(
        repository_for(2), wrong_history, fake_review, time_tool=fake_time
    )
    result = await graph.ainvoke(initial_state())

    assert result["comparison_status"] == "tool_unavailable"
    assert result["comparison_result"] is None
    assert result["comparison_error"] == "MCP_HISTORY_CASE_MISMATCH"
    assert result["status"] == "awaiting_clinician_review"


@pytest.mark.asyncio
async def test_review_submission_failure_is_not_reported_as_queued():
    async def broken_review(request):
        raise RuntimeError("MCP connection lost")

    graph = build_mcp_triage_graph(
        repository_for(2), fake_history, broken_review, time_tool=fake_time
    )
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

    graph = build_mcp_triage_graph(
        repository_for(2), fake_history, wrong_review, time_tool=fake_time
    )
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

    first_calls = MCPToolCallRepository(database).get_by_workflow_run(
        first["workflow_run_id"]
    )
    second_calls = MCPToolCallRepository(database).get_by_workflow_run(
        second["workflow_run_id"]
    )
    assert first["workflow_run_id"] != second["workflow_run_id"]
    assert [call.tool_name for call in first_calls] == [
        "get_current_time",
        "compare_with_history",
        "determine_priority",
        "submit_review_request",
    ]
    assert all(call.status == "success" for call in first_calls + second_calls)


@pytest.mark.asyncio
async def test_successful_review_is_confirmed_when_only_audit_write_fails(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "workflow-audit-failure.sqlite3")
    database.initialize()
    repository = ObservationRepository(database)
    for record in make_timeline(2).records:
        repository.save(record)

    def fail_append(self, record):
        raise sqlite3.OperationalError("synthetic audit failure")

    monkeypatch.setattr(MCPToolCallRepository, "append", fail_append)
    result = await build_mcp_triage_graph(repository).ainvoke(initial_state())

    assert result["status"] == "awaiting_clinician_review"
    assert result["review_submission_status"] == "persisted"
    assert result["review_request_id"]
    assert result["mcp_audit_errors"] == [
        "get_current_time:MCP_AUDIT_PERSISTENCE_FAILED",
        "compare_with_history:MCP_AUDIT_PERSISTENCE_FAILED",
        "determine_priority:MCP_AUDIT_PERSISTENCE_FAILED",
        "submit_review_request:MCP_AUDIT_PERSISTENCE_FAILED",
    ]
    assert (
        ReviewRepository(database).get_pending()[0].request_id
        == result["review_request_id"]
    )


@pytest.mark.asyncio
async def test_review_timeout_reconciles_matching_persisted_request(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "review-timeout-persisted.sqlite3")
    database.initialize()
    repository = ObservationRepository(database)

    for record in make_timeline(2).records:
        repository.save(record)

    reviews = ReviewRepository(database)
    reviews.initialize()
    submitted = []

    async def persist_then_timeout(request, database_path, *, workflow_run_id):
        saved = reviews.submit(request)
        submitted.append(saved.request_id)
        raise TimeoutError("Synthetic lost MCP response")

    async def priority(request):
        return determine_priority(request)

    monkeypatch.setattr(
        "tazama.orchestration.mcp_graph.submit_review_via_mcp",
        persist_then_timeout,
    )

    graph = build_mcp_triage_graph(
        repository,
        history_tool=fake_history,
        priority_tool=priority,
        time_tool=fake_time,
    )

    result = await graph.ainvoke(initial_state())

    assert result["review_submission_status"] == "persisted"
    assert result["status"] == "awaiting_clinician_review"
    assert result["review_request_id"] == submitted[0]
    assert len(reviews.get_pending()) == 1

    with database.connect() as connection:
        event_count = connection.execute(
            "SELECT COUNT(*) FROM review_request_events"
        ).fetchone()[0]

    assert event_count == 1


@pytest.mark.asyncio
async def test_review_timeout_without_persistence_remains_unconfirmed(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "review-timeout-absent.sqlite3")
    database.initialize()
    repository = ObservationRepository(database)

    for record in make_timeline(2).records:
        repository.save(record)

    reviews = ReviewRepository(database)
    reviews.initialize()

    async def timeout_before_persistence(request, database_path, *, workflow_run_id):
        raise TimeoutError("Synthetic MCP timeout before persistence")

    async def priority(request):
        return determine_priority(request)

    monkeypatch.setattr(
        "tazama.orchestration.mcp_graph.submit_review_via_mcp",
        timeout_before_persistence,
    )

    graph = build_mcp_triage_graph(
        repository,
        history_tool=fake_history,
        priority_tool=priority,
        time_tool=fake_time,
    )

    result = await graph.ainvoke(initial_state())

    assert result["review_submission_status"] == "unconfirmed"
    assert result["review_request_id"] is None
    assert result["review_submission_error"] == ("MCP_REVIEW_SUBMISSION_UNCONFIRMED")
    assert result["status"] == "review_submission_failed"
    assert reviews.get_pending() == []

    with database.connect() as connection:
        event_count = connection.execute(
            "SELECT COUNT(*) FROM review_request_events"
        ).fetchone()[0]

    assert event_count == 0


@pytest.mark.asyncio
async def test_review_timeout_rejects_conflicting_persisted_evidence(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "review-timeout-conflict.sqlite3")
    database.initialize()
    repository = ObservationRepository(database)

    for record in make_timeline(2).records:
        repository.save(record)

    reviews = ReviewRepository(database)
    reviews.initialize()

    async def conflicting_persistence_then_timeout(
        request, database_path, *, workflow_run_id
    ):
        conflicting = request.model_copy(
            update={"comparison_status": "conflicting_status"}
        )
        reviews.submit(conflicting)
        raise TimeoutError("Synthetic lost MCP response")

    async def priority(request):
        return determine_priority(request)

    monkeypatch.setattr(
        "tazama.orchestration.mcp_graph.submit_review_via_mcp",
        conflicting_persistence_then_timeout,
    )

    graph = build_mcp_triage_graph(
        repository,
        history_tool=fake_history,
        priority_tool=priority,
        time_tool=fake_time,
    )

    result = await graph.ainvoke(initial_state())

    assert result["review_submission_status"] == "unconfirmed"
    assert result["review_request_id"] is None
    assert result["status"] == "review_submission_failed"

    saved = reviews.get_by_observation_id("OBS-2")
    assert saved is not None
    assert saved.comparison_status == "conflicting_status"

    with database.connect() as connection:
        event_count = connection.execute(
            "SELECT COUNT(*) FROM review_request_events"
        ).fetchone()[0]

    assert event_count == 1


@pytest.mark.asyncio
async def test_review_timeout_reconciliation_lookup_failure(tmp_path, monkeypatch):
    database = Database(tmp_path / "review-timeout-lookup-failure.sqlite3")
    database.initialize()
    repository = ObservationRepository(database)

    for record in make_timeline(2).records:
        repository.save(record)

    reviews = ReviewRepository(database)
    reviews.initialize()

    async def timeout_submission(request, database_path, *, workflow_run_id):
        raise TimeoutError("Synthetic lost MCP response")

    def failed_lookup(self, observation_id):
        raise sqlite3.OperationalError("Synthetic database lookup failure")

    async def priority(request):
        return determine_priority(request)

    monkeypatch.setattr(
        "tazama.orchestration.mcp_graph.submit_review_via_mcp",
        timeout_submission,
    )
    monkeypatch.setattr(
        ReviewRepository,
        "get_by_observation_id",
        failed_lookup,
    )

    graph = build_mcp_triage_graph(
        repository,
        history_tool=fake_history,
        priority_tool=priority,
        time_tool=fake_time,
    )

    result = await graph.ainvoke(initial_state())

    assert result["review_submission_status"] == "unconfirmed"
    assert result["review_request_id"] is None
    assert result["status"] == "review_submission_failed"
    assert (
        "submit_review_request:RECONCILIATION_LOOKUP_FAILED"
        in result["mcp_audit_errors"]
    )

    with database.connect() as connection:
        event_count = connection.execute(
            "SELECT COUNT(*) FROM review_request_events"
        ).fetchone()[0]

    assert event_count == 0


@pytest.mark.asyncio
async def test_injected_review_timeout_does_not_reconcile(tmp_path, monkeypatch):
    database = Database(tmp_path / "injected-review-timeout.sqlite3")
    database.initialize()
    repository = ObservationRepository(database)

    for record in make_timeline(2).records:
        repository.save(record)

    reviews = ReviewRepository(database)
    reviews.initialize()
    lookup_calls = []

    def unexpected_lookup(self, observation_id):
        lookup_calls.append(observation_id)
        raise AssertionError("Injected review tools must not reconcile")

    async def timeout_review(request):
        raise TimeoutError("Synthetic injected review timeout")

    async def priority(request):
        return determine_priority(request)

    monkeypatch.setattr(
        ReviewRepository,
        "get_by_observation_id",
        unexpected_lookup,
    )

    graph = build_mcp_triage_graph(
        repository,
        history_tool=fake_history,
        review_tool=timeout_review,
        priority_tool=priority,
        time_tool=fake_time,
    )

    result = await graph.ainvoke(initial_state())

    assert result["review_submission_status"] == "unconfirmed"
    assert result["review_request_id"] is None
    assert result["status"] == "review_submission_failed"
    assert lookup_calls == []
    assert reviews.get_pending() == []
