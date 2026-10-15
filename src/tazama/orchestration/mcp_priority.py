"""MCP stdio client for deterministic priority assessment."""

import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tazama.clinical.priority import PriorityResult
from tazama.mcp.priority_contract import DeterminePriorityRequest
from tazama.orchestration.mcp_audit import (
    MCPResponseError,
    MCPToolError,
    audited_mcp_call,
)


async def determine_priority_via_mcp(
    request: DeterminePriorityRequest,
    *, workflow_run_id: str, database_path: str | Path,
) -> PriorityResult:
    """Call the real deterministic priority MCP tool."""
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tazama.mcp.server"],
    )

    arguments = {"request": request.model_dump(mode="json")}
    async def operation() -> PriorityResult:
        async with (stdio_client(server) as (read, write), ClientSession(read, write) as session):
            await session.initialize()
            response = await session.call_tool("determine_priority", arguments=arguments)
        if response.isError:
            raise MCPToolError("MCP_PRIORITY_TOOL_ERROR")
        payload = response.structuredContent
        if payload is None:
            if not response.content or response.content[0].type != "text":
                raise MCPResponseError("MCP_PRIORITY_RESPONSE_EMPTY")
            payload = json.loads(response.content[0].text)
        if isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        return PriorityResult.model_validate(payload)
    return await audited_mcp_call(
        database_path=database_path, workflow_run_id=workflow_run_id,
        server_name="tazama-clinical", tool_name="determine_priority",
        arguments=arguments, operation=operation,
    )
