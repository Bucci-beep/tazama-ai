"""Timeout regression tests for the History MCP client."""

import asyncio

import pytest

from tazama.clinical.history import CompareHistoryRequest, TimedObservation
from tazama.orchestration import mcp_history
from tazama.storage.database import Database
from tazama.storage.mcp_audit import MCPToolCallRepository


@pytest.mark.asyncio
async def test_hanging_history_mcp_call_times_out_and_is_audited(tmp_path, monkeypatch):
    database_path = tmp_path / "history-timeout.sqlite3"
    Database(database_path).initialize()

    request = CompareHistoryRequest.model_construct(
        case_id="SYNTHETIC-001",
        before=None,
        after=TimedObservation.model_construct(
            obs_id="OBS-001",
            taken_utc="2026-10-27T12:00:00+00:00",
            observations=None,
        ),
    )

    class HangingStdio:
        async def __aenter__(self):
            await asyncio.Event().wait()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        mcp_history,
        "stdio_client",
        lambda server: HangingStdio(),
    )

    original_audited_call = mcp_history.audited_mcp_call

    async def short_deadline_call(**kwargs):
        kwargs["timeout_seconds"] = 0.05
        return await original_audited_call(**kwargs)

    monkeypatch.setattr(
        mcp_history,
        "audited_mcp_call",
        short_deadline_call,
    )

    with pytest.raises(TimeoutError):
        await mcp_history.compare_history_via_mcp(
            request,
            workflow_run_id="RUN-HISTORY-TIMEOUT",
            database_path=database_path,
        )

    calls = MCPToolCallRepository(Database(database_path)).get_by_workflow_run(
        "RUN-HISTORY-TIMEOUT"
    )

    assert len(calls) == 1
    assert calls[0].tool_name == "compare_with_history"
    assert calls[0].status == "transport_error"
    assert calls[0].error["type"] == "TimeoutError"
