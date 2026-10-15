"""Focused MCP audit logging tests."""

import sqlite3

import pytest

from tazama.orchestration.mcp_audit import (
    MCPAuditPersistenceError,
    MCPToolError,
    audited_mcp_call,
)
from tazama.storage.database import Database
from tazama.storage.mcp_audit import MCPToolCallRepository


@pytest.mark.asyncio
async def test_successful_call_writes_audit_record(tmp_path):
    database = Database(tmp_path / "audit.sqlite3")
    database.initialize()

    async def success():
        return {"result": "ok"}

    result = await audited_mcp_call(
        database_path=database.database_path,
        workflow_run_id="RUN-SUCCESS-001",
        server_name="synthetic-test-server",
        tool_name="successful_tool",
        arguments={"value": 1},
        operation=success,
    )

    calls = MCPToolCallRepository(database).get_by_workflow_run("RUN-SUCCESS-001")
    assert result == {"result": "ok"}
    assert len(calls) == 1
    assert calls[0].status == "success"
    assert calls[0].output == result


@pytest.mark.asyncio
async def test_successful_call_surfaces_audit_write_failure_with_result(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "audit.sqlite3")
    database.initialize()

    async def success():
        return {"result": "MCP_COMPLETED"}

    def fail_append(self, record):
        raise sqlite3.OperationalError("synthetic audit failure")

    monkeypatch.setattr(MCPToolCallRepository, "append", fail_append)

    with pytest.raises(MCPAuditPersistenceError) as caught:
        await audited_mcp_call(
            database_path=database.database_path,
            workflow_run_id="RUN-AUDIT-FAIL-001",
            server_name="synthetic-test-server",
            tool_name="successful_tool",
            arguments={},
            operation=success,
        )

    assert caught.value.result == {"result": "MCP_COMPLETED"}
    assert str(caught.value) == "MCP_AUDIT_PERSISTENCE_FAILED"


@pytest.mark.asyncio
async def test_failed_call_preserves_mcp_error_when_audit_write_also_fails(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "audit.sqlite3")
    database.initialize()

    async def failure():
        raise MCPToolError("ACTUAL_MCP_FAILURE")

    def fail_append(self, record):
        raise sqlite3.OperationalError("synthetic audit failure")

    monkeypatch.setattr(MCPToolCallRepository, "append", fail_append)

    with pytest.raises(MCPToolError, match="ACTUAL_MCP_FAILURE") as caught:
        await audited_mcp_call(
            database_path=database.database_path,
            workflow_run_id="RUN-DOUBLE-FAIL-001",
            server_name="synthetic-test-server",
            tool_name="failed_tool",
            arguments={},
            operation=failure,
        )

    assert caught.value.audit_persistence_failed is True
    assert caught.value.__notes__ == [
        "MCP audit persistence failed: OperationalError"
    ]


@pytest.mark.asyncio
async def test_failed_call_is_sanitised_correlated_and_does_not_change_handling(tmp_path):
    database = Database(tmp_path / "audit.sqlite3")
    database.initialize()

    async def failure():
        raise MCPToolError("EXPECTED_TOOL_FAILURE")

    with pytest.raises(MCPToolError, match="EXPECTED_TOOL_FAILURE"):
        await audited_mcp_call(
            database_path=database.database_path,
            workflow_run_id="RUN-FAIL-001",
            server_name="synthetic-test-server",
            tool_name="synthetic_failure",
            arguments={"case_id": "SYNTHETIC-001", "access_token": "never-store"},
            operation=failure,
        )

    calls = MCPToolCallRepository(database).get_by_workflow_run("RUN-FAIL-001")
    assert len(calls) == 1
    assert calls[0].status == "tool_error"
    assert calls[0].input_arguments["access_token"] == "[REDACTED]"
    assert calls[0].error == {
        "type": "MCPToolError",
        "message": "EXPECTED_TOOL_FAILURE",
    }
    assert calls[0].duration_ms >= 0


def test_mcp_audit_table_is_append_only(tmp_path):
    database = Database(tmp_path / "audit.sqlite3")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO mcp_tool_calls VALUES (
                'INV-1', 'RUN-1', 'server', 'tool',
                '2026-10-15T00:00:00+00:00', '2026-10-15T00:00:00+00:00',
                '{}', '{}', NULL, 'success', 0
            )
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM mcp_tool_calls")
