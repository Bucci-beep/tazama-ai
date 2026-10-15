"""Integration test for the official third-party Time MCP server."""

from datetime import UTC

import pytest

from tazama.orchestration.mcp_time import get_current_utc_via_mcp
from tazama.storage.database import Database
from tazama.storage.mcp_audit import MCPToolCallRepository


@pytest.mark.asyncio
async def test_official_time_mcp_returns_typed_utc_context(tmp_path):
    database = Database(tmp_path / "time.sqlite3")
    database.initialize()
    result = await get_current_utc_via_mcp(
        workflow_run_id="RUN-TIME-001",
        database_path=database.database_path,
    )

    assert result.timezone == "UTC"
    assert result.datetime.utcoffset() == UTC.utcoffset(result.datetime)
    assert result.day_of_week
    assert result.is_dst is False
    calls = MCPToolCallRepository(database).get_by_workflow_run("RUN-TIME-001")
    assert len(calls) == 1
    assert calls[0].server_name == "mcp-server-time"
    assert calls[0].status == "success"
