"""Typed stdio client for the official third-party Time MCP server."""

import asyncio
import json
import sys
from datetime import UTC, datetime
from typing import Literal

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator


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


async def get_current_utc_via_mcp(timeout_seconds: float = 5.0) -> TimeContext:
    """Call the official Time MCP server with a bounded stdio session."""
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server_time", "--local-timezone=UTC"],
    )

    async with asyncio.timeout(timeout_seconds):
        async with (
            stdio_client(server) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            response = await session.call_tool(
                "get_current_time",
                arguments={"timezone": "UTC"},
            )

    if response.isError:
        raise RuntimeError("MCP_TIME_TOOL_ERROR")

    payload = response.structuredContent
    if payload is None:
        if not response.content or response.content[0].type != "text":
            raise RuntimeError("MCP_TIME_RESPONSE_EMPTY")
        payload = json.loads(response.content[0].text)
    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]

    return TimeContext.model_validate(payload)
