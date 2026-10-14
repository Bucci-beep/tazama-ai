"""MCP stdio client for deterministic priority assessment."""

import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tazama.clinical.priority import PriorityResult
from tazama.mcp.priority_contract import DeterminePriorityRequest


async def determine_priority_via_mcp(
    request: DeterminePriorityRequest,
) -> PriorityResult:
    """Call the real deterministic priority MCP tool."""
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tazama.mcp.server"],
    )

    async with (
        stdio_client(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        response = await session.call_tool(
            "determine_priority",
            arguments={"request": request.model_dump(mode="json")},
        )

    if response.isError:
        raise RuntimeError("MCP_PRIORITY_TOOL_ERROR")

    payload = response.structuredContent
    if payload is None:
        if not response.content or response.content[0].type != "text":
            raise RuntimeError("MCP_PRIORITY_RESPONSE_EMPTY")
        payload = json.loads(response.content[0].text)
    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]
    return PriorityResult.model_validate(payload)
