"""MCP stdio client for the existing history-comparison tool."""

import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tazama.clinical.history import CompareHistoryRequest, CompareHistoryResult


async def compare_history_via_mcp(
    request: CompareHistoryRequest,
) -> CompareHistoryResult:
    """Call the actual Tazama MCP server, not the underlying Python function."""
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
            "compare_with_history",
            arguments={"request": request.model_dump(mode="json")},
        )

    if response.isError:
        raise RuntimeError("MCP_HISTORY_TOOL_ERROR")

    payload = response.structuredContent

    if payload is None:
        if not response.content:
            raise RuntimeError("MCP_HISTORY_RESPONSE_EMPTY")
        first = response.content[0]
        if first.type != "text":
            raise RuntimeError("MCP_HISTORY_RESPONSE_NOT_TEXT")
        payload = json.loads(first.text)

    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]

    return CompareHistoryResult.model_validate(payload)
