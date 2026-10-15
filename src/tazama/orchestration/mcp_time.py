"""Typed stdio client for the official third-party Time MCP server."""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from tazama.orchestration.mcp_audit import (
    MCPResponseError,
    MCPToolError,
    audited_mcp_call,
)


class TimeContext(BaseModel):
    """Validated UTC provenance returned by the borrowed MCP server."""

    model_config = ConfigDict(extra="forbid")

    timezone: Literal["UTC"]
    datetime: AwareDatetime
    day_of_week: str
    is_dst: bool

    @field_validator("datetime")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("Time MCP response must be UTC")
        return value.astimezone(UTC)


async def get_current_utc_via_mcp(
    *, workflow_run_id: str, database_path: str | Path, timeout_seconds: float = 5.0
) -> TimeContext:
    """Call the official Time MCP server with a bounded stdio session."""
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server_time", "--local-timezone=UTC"],
    )

    async def operation() -> TimeContext:
        async with asyncio.timeout(timeout_seconds):
            async with (
                stdio_client(server) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                response = await session.call_tool("get_current_time", arguments={"timezone": "UTC"})
        if response.isError:
            raise MCPToolError("MCP_TIME_TOOL_ERROR")
        payload = response.structuredContent
        if payload is None:
            if not response.content or response.content[0].type != "text":
                raise MCPResponseError("MCP_TIME_RESPONSE_EMPTY")
            payload = json.loads(response.content[0].text)
        if isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        return TimeContext.model_validate(payload)

    return await audited_mcp_call(
        database_path=database_path, workflow_run_id=workflow_run_id,
        server_name="mcp-server-time", tool_name="get_current_time",
        arguments={"timezone": "UTC"}, operation=operation,
    )
