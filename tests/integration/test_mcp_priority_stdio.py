"""Integration tests for determine_priority over a real MCP stdio subprocess."""

import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

NORMAL = {
    "heart_rate_bpm": 80.0,
    "respiratory_rate_bpm": 12.0,
    "systolic_bp_mmhg": 120.0,
    "temperature_c": 37.0,
    "consciousness": "alert",
    "mobility": "walking",
    "trauma": False,
}


@pytest.fixture
def server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "tazama.mcp.server"],
    )


async def call_priority(server_parameters, request):
    async with (
        stdio_client(server_parameters) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(
            "determine_priority", arguments={"request": request}
        )

    assert not result.isError
    payload = result.structuredContent
    assert payload is not None
    return payload


@pytest.mark.asyncio
async def test_emergency_sign_gives_emergency_without_vitals(server_parameters):
    payload = await call_priority(
        server_parameters,
        {
            "schema_version": "1.0",
            "case_id": "SYN-210",
            "observations": {},
            "signs": ["DISC/EMERGENCY/NOT_BREATHING"],
        },
    )

    assert payload["status"] == "complete"
    assert payload["priority"] == "emergency"


@pytest.mark.asyncio
async def test_signs_not_assessed_gives_a_minimum_only(server_parameters):
    payload = await call_priority(
        server_parameters,
        {
            "schema_version": "1.0",
            "case_id": "SYN-211",
            "observations": NORMAL,
        },
    )

    assert payload["status"] == "minimum_only"
    assert payload["priority"] is None
    assert payload["priority_at_least"] == "routine"


@pytest.mark.asyncio
async def test_unknown_sign_abstains(server_parameters):
    payload = await call_priority(
        server_parameters,
        {
            "schema_version": "1.0",
            "case_id": "SYN-212",
            "observations": NORMAL,
            "signs": ["DISC/NOT/A_REAL_SIGN"],
        },
    )

    assert payload["status"] == "abstained"
    assert payload["priority"] is None
