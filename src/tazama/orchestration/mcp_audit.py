"""Reusable execution wrapper for audited MCP calls."""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic_ns
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from tazama.storage.database import Database
from tazama.storage.mcp_audit import (
    MCPStatus,
    MCPToolCall,
    MCPToolCallRepository,
    sanitise,
)


class MCPToolError(RuntimeError):
    """The MCP server returned a tool-level error."""


class MCPResponseError(RuntimeError):
    """The MCP response could not be validated."""


class MCPAuditPersistenceError[T](RuntimeError):
    """A successful MCP result whose audit record could not be persisted."""

    def __init__(self, result: T) -> None:
        super().__init__("MCP_AUDIT_PERSISTENCE_FAILED")
        self.result = result


def _status_for(error: Exception) -> MCPStatus:
    if isinstance(error, MCPToolError):
        return "tool_error"
    if isinstance(error, (MCPResponseError, ValidationError, json.JSONDecodeError, ValueError)):
        return "validation_error"
    return "transport_error"


async def audited_mcp_call[T](
    *,
    database_path: str | Path,
    workflow_run_id: str,
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    operation: Callable[[], Awaitable[T]],
) -> T:
    """Run an MCP operation and persist its sanitised success or failure."""
    invocation_id = str(uuid4())
    started_at = datetime.now(UTC)
    started_ns = monotonic_ns()
    try:
        result = await operation()
    except Exception as error:
        completed_at = datetime.now(UTC)
        try:
            MCPToolCallRepository(Database(database_path)).append(
                MCPToolCall(
                    invocation_id=invocation_id,
                    workflow_run_id=workflow_run_id,
                    server_name=server_name,
                    tool_name=tool_name,
                    started_at=started_at,
                    completed_at=completed_at,
                    input_arguments=sanitise(arguments),
                    error={"type": type(error).__name__, "message": str(error)},
                    status=_status_for(error),
                    duration_ms=max(0, (monotonic_ns() - started_ns) // 1_000_000),
                )
            )
        except Exception as audit_error:  # noqa: BLE001
            error.add_note(
                f"MCP audit persistence failed: {type(audit_error).__name__}"
            )
            error.audit_persistence_failed = True
        raise
    completed_at = datetime.now(UTC)
    try:
        MCPToolCallRepository(Database(database_path)).append(
            MCPToolCall(
                invocation_id=invocation_id,
                workflow_run_id=workflow_run_id,
                server_name=server_name,
                tool_name=tool_name,
                started_at=started_at,
                completed_at=completed_at,
                input_arguments=sanitise(arguments),
                output=sanitise(result),
                status="success",
                duration_ms=max(0, (monotonic_ns() - started_ns) // 1_000_000),
            )
        )
    except Exception as error:
        raise MCPAuditPersistenceError(result) from error
    return result
