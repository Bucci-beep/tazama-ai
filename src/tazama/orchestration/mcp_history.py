"""MCP stdio client for the existing history-comparison tool."""

import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tazama.clinical.history import CompareHistoryRequest, CompareHistoryResult
from tazama.orchestration.mcp_audit import (
    MCPResponseError,
    MCPToolError,
    audited_mcp_call,
)


async def compare_history_via_mcp(
    request: CompareHistoryRequest,
    *, workflow_run_id: str, database_path: str | Path,
) -> CompareHistoryResult:
    """Call the actual Tazama MCP server, not the underlying Python function."""
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tazama.mcp.server"],
    )

    arguments = {"request": request.model_dump(mode="json")}
    async def operation() -> CompareHistoryResult:
        async with (stdio_client(server) as (read, write), ClientSession(read, write) as session):
            await session.initialize()
            response = await session.call_tool("compare_with_history", arguments=arguments)
        if response.isError:
            raise MCPToolError("MCP_HISTORY_TOOL_ERROR")
        payload = response.structuredContent
        if payload is None:
            if not response.content or response.content[0].type != "text":
                raise MCPResponseError("MCP_HISTORY_RESPONSE_EMPTY")
            payload = json.loads(response.content[0].text)
        if isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        return CompareHistoryResult.model_validate(payload)
    return await audited_mcp_call(
        database_path=database_path, workflow_run_id=workflow_run_id,
        server_name="tazama-clinical", tool_name="compare_with_history",
        arguments=arguments, operation=operation,
    )
