"""Append-only local audit records for MCP tool invocations."""

import json
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from tazama.storage.database import Database

MCPStatus = Literal["success", "tool_error", "validation_error", "transport_error"]
_SENSITIVE_KEYS = ("authorization", "cookie", "credential", "password", "secret", "token")


def sanitise(value: Any, *, depth: int = 0) -> Any:
    """Convert supported values to bounded JSON data and redact secret-like fields."""
    if depth > 12:
        return "[TRUNCATED]"
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:4000] + ("[TRUNCATED]" if len(value) > 4000 else "")
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(marker in str(key).lower() for marker in _SENSITIVE_KEYS)
                else sanitise(item, depth=depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitise(item, depth=depth + 1) for item in value[:1000]]
    return str(value)[:4000]


class MCPToolCall(BaseModel):
    """A single completed MCP invocation."""

    model_config = ConfigDict(extra="forbid")
    invocation_id: str
    workflow_run_id: str
    server_name: str
    tool_name: str
    started_at: AwareDatetime
    completed_at: AwareDatetime
    input_arguments: dict[str, Any]
    output: Any | None = None
    error: dict[str, Any] | None = None
    status: MCPStatus
    duration_ms: int


class MCPToolCallRepository:
    """Persist and query append-only MCP tool call records."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def append(self, record: MCPToolCall) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO mcp_tool_calls (
                    invocation_id, workflow_run_id, server_name, tool_name,
                    started_at, completed_at, input_json, output_json,
                    error_json, status, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.invocation_id,
                    record.workflow_run_id,
                    record.server_name,
                    record.tool_name,
                    record.started_at.isoformat(),
                    record.completed_at.isoformat(),
                    json.dumps(record.input_arguments, sort_keys=True),
                    json.dumps(record.output, sort_keys=True) if record.output is not None else None,
                    json.dumps(record.error, sort_keys=True) if record.error is not None else None,
                    record.status,
                    record.duration_ms,
                ),
            )

    def get_by_workflow_run(self, workflow_run_id: str) -> list[MCPToolCall]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT invocation_id, workflow_run_id, server_name, tool_name,
                       started_at, completed_at, input_json, output_json,
                       error_json, status, duration_ms
                FROM mcp_tool_calls
                WHERE workflow_run_id = ?
                ORDER BY started_at, invocation_id
                """,
                (workflow_run_id,),
            ).fetchall()
        return [
            MCPToolCall(
                invocation_id=row[0], workflow_run_id=row[1], server_name=row[2],
                tool_name=row[3], started_at=row[4], completed_at=row[5],
                input_arguments=json.loads(row[6]),
                output=json.loads(row[7]) if row[7] is not None else None,
                error=json.loads(row[8]) if row[8] is not None else None,
                status=row[9], duration_ms=row[10],
            )
            for row in rows
        ]
