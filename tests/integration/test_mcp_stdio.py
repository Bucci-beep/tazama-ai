"""Integration tests using a real MCP stdio subprocess."""

import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.fixture
def server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "tazama.mcp.server"],
    )


@pytest.mark.asyncio
async def test_mcp_tools_are_discoverable(server_parameters):
    async with (
        stdio_client(server_parameters) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}

        assert "validate_observations" in names
        assert "calculate_sats" in names


@pytest.mark.asyncio
async def test_mcp_validation_preserves_missing_data(server_parameters):
    async with (
        stdio_client(server_parameters) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        result = await session.call_tool(
            "validate_observations",
            arguments={
                "request": {
                    "schema_version": "1.0",
                    "case_id": "SYN-001",
                    "observations": {
                        "heart_rate_bpm": 90.0,
                        "temperature_c": 37.0,
                    },
                }
            },
        )

        assert not result.isError

        payload = result.structuredContent
        assert payload is not None

        assert payload["status"] == "pending_protocol"
        assert "respiratory_rate_bpm" in payload["missing_fields"]
        assert "systolic_bp_mmhg" in payload["missing_fields"]


@pytest.mark.asyncio
async def test_mcp_scoring_never_invents_priority(server_parameters):
    async with (
        stdio_client(server_parameters) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        result = await session.call_tool(
            "calculate_sats",
            arguments={
                "request": {
                    "schema_version": "1.0",
                    "case_id": "SYN-002",
                    "observations": {
                        "heart_rate_bpm": 90.0,
                    },
                }
            },
        )

        assert not result.isError

        payload = result.structuredContent
        assert payload is not None

        assert payload["status"] == "unavailable"
        assert payload["priority"] is None
        assert payload["protocol_version"] is None
        assert payload["next_action"] == "human_clinical_assessment"


@pytest.mark.asyncio
async def test_mcp_rejects_unsupported_schema_version(server_parameters):
    async with (
        stdio_client(server_parameters) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        result = await session.call_tool(
            "calculate_sats",
            arguments={
                "request": {
                    "schema_version": "2.0",
                    "case_id": "SYN-003",
                    "observations": {},
                }
            },
        )

        assert result.isError
