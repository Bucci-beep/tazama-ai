"""Integration test for the official third-party Time MCP server."""

from datetime import UTC

import pytest

from tazama.orchestration.mcp_time import get_current_utc_via_mcp


@pytest.mark.asyncio
async def test_official_time_mcp_returns_typed_utc_context():
    result = await get_current_utc_via_mcp()

    assert result.timezone == "UTC"
    assert result.datetime.utcoffset() == UTC.utcoffset(result.datetime)
    assert result.day_of_week
    assert result.is_dst is False
