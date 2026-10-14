"""LangGraph-to-MCP integration tests using synthetic patient data."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from tazama.clinical.history import CompareHistoryResult
from tazama.mcp.contracts import PatientObservations
from tazama.orchestration.mcp_graph import build_mcp_triage_graph
from tazama.patients.models import ObservationRecord, PatientTimeline


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
                observations=PatientObservations(heart_rate_bpm=float(80 + index * 10)),
            )
        )

    return timeline


def repository_for(count: int):
    repo = Mock()
    repo.get_timeline.return_value = make_timeline(count)
    return repo


def initial_state(case_id="CASE-MCP-001"):
    return {"case_id": case_id, "status": "pending", "reason": None}


@pytest.mark.asyncio
async def test_comparison_uses_latest_two_observations():
    received = []

    async def fake_tool(request):
        received.append(request)
        return CompareHistoryResult(
            case_id=request.case_id,
            status="differences_found",
        )

    graph = build_mcp_triage_graph(repository_for(3), fake_tool)
    result = await graph.ainvoke(initial_state())

    assert received[0].before.obs_id == "OBS-2"
    assert received[0].after.obs_id == "OBS-3"
    assert result["comparison_status"] == "differences_found"
    assert result["status"] == "awaiting_clinician_review"


@pytest.mark.asyncio
async def test_empty_timeline_skips_mcp():
    calls = []

    async def fake_tool(request):
        calls.append(request)
        raise AssertionError("MCP should not be called")

    graph = build_mcp_triage_graph(repository_for(0), fake_tool)
    result = await graph.ainvoke(initial_state())

    assert calls == []
    assert result["comparison_status"] == "insufficient_history"
    assert result["comparison_result"]["reason"] == "NO_OBSERVATIONS"


@pytest.mark.asyncio
async def test_mcp_failure_does_not_produce_reassuring_result():
    async def broken_tool(request):
        raise RuntimeError("Connection failed")

    graph = build_mcp_triage_graph(repository_for(2), broken_tool)
    result = await graph.ainvoke(initial_state())

    assert result["comparison_status"] == "tool_unavailable"
    assert result["comparison_result"] is None
    assert result["comparison_error"] == "MCP_HISTORY_TOOL_UNAVAILABLE"
    assert result["status"] == "awaiting_clinician_review"


@pytest.mark.asyncio
async def test_invalid_case_never_queries_sqlite_or_mcp():
    repo = repository_for(2)

    async def fake_tool(request):
        raise AssertionError("MCP should not be called")

    graph = build_mcp_triage_graph(repo, fake_tool)
    result = await graph.ainvoke(initial_state("  "))

    repo.get_timeline.assert_not_called()
    assert result["status"] == "invalid_input"


@pytest.mark.asyncio
async def test_mismatched_mcp_case_is_not_accepted():
    async def wrong_case_tool(request):
        return CompareHistoryResult(
            case_id="DIFFERENT-CASE",
            status="no_differences",
        )

    graph = build_mcp_triage_graph(repository_for(2), wrong_case_tool)
    result = await graph.ainvoke(initial_state())

    assert result["comparison_status"] == "tool_unavailable"
    assert result["comparison_result"] is None
    assert result["comparison_error"] == "MCP_HISTORY_CASE_MISMATCH"


@pytest.mark.asyncio
async def test_real_mcp_stdio_tool():
    """Exercise the actual MCP server with synthetic observations."""
    graph = build_mcp_triage_graph(repository_for(2))
    result = await graph.ainvoke(initial_state())

    assert result["comparison_status"] == "differences_found", result
    assert result["comparison_result"]["changes"][0]["field"] == ("heart_rate_bpm")
    assert result["comparison_error"] is None
    assert result["status"] == "awaiting_clinician_review"
