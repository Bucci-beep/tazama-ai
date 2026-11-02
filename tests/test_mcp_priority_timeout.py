"""Timeout regression tests for deterministic Priority MCP."""

import asyncio

import pytest

from tazama.mcp.priority_contract import DeterminePriorityRequest
from tazama.orchestration import mcp_priority
from tazama.storage.database import Database
from tazama.storage.mcp_audit import MCPToolCallRepository


@pytest.mark.asyncio
async def test_hanging_priority_mcp_call_times_out_without_priority(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "priority-timeout.sqlite3"
    Database(database_path).initialize()

    request = DeterminePriorityRequest.model_construct(
        case_id="SYNTHETIC-001",
    )

    class HangingStdio:
        async def __aenter__(self):
            await asyncio.Event().wait()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        mcp_priority,
        "stdio_client",
        lambda server: HangingStdio(),
    )

    original_audited_call = mcp_priority.audited_mcp_call

    async def short_deadline_call(**kwargs):
        kwargs["timeout_seconds"] = 0.05
        return await original_audited_call(**kwargs)

    monkeypatch.setattr(
        mcp_priority,
        "audited_mcp_call",
        short_deadline_call,
    )

    with pytest.raises(TimeoutError):
        await mcp_priority.determine_priority_via_mcp(
            request,
            workflow_run_id="RUN-PRIORITY-TIMEOUT",
            database_path=database_path,
        )

    calls = MCPToolCallRepository(Database(database_path)).get_by_workflow_run(
        "RUN-PRIORITY-TIMEOUT"
    )

    assert len(calls) == 1
    assert calls[0].tool_name == "determine_priority"
    assert calls[0].status == "transport_error"
    assert calls[0].error["type"] == "TimeoutError"
    assert calls[0].output is None
