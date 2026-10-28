"""MCP stdio client for persistent clinician review submission."""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tazama.orchestration.mcp_audit import (
    MCPResponseError,
    MCPToolError,
    audited_mcp_call,
)
from tazama.storage.reviews import (
    ReviewAttestation,
    ReviewRequest,
    SubmitAttestation,
    SubmitReviewRequest,
    deterministic_evidence,
)


async def submit_review_via_mcp(
    request: SubmitReviewRequest,
    database_path: str | Path,
    *,
    workflow_run_id: str | None = None,
) -> ReviewRequest:
    """Submit evidence through MCP without approving a clinical decision."""
    path = Path(database_path).expanduser().resolve()

    if not path.is_file():
        raise ValueError("The configured SQLite database does not exist")

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tazama.mcp.server"],
        env={
            **os.environ,
            "TAZAMA_DB_PATH": str(path),
        },
    )

    arguments = {"request": request.model_dump(mode="json")}

    async def operation() -> ReviewRequest:
        async with (
            stdio_client(server) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            response = await session.call_tool(
                "submit_review_request", arguments=arguments
            )
        if response.isError:
            raise MCPToolError("MCP_REVIEW_SUBMISSION_FAILED")
        payload = response.structuredContent
        if payload is None:
            if not response.content or response.content[0].type != "text":
                raise MCPResponseError("MCP_REVIEW_RESPONSE_EMPTY")
            payload = json.loads(response.content[0].text)
        if isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        result = ReviewRequest.model_validate_json(json.dumps(payload))
        if (
            result.case_id != request.case_id
            or result.observation_id != request.observation_id
            or result.comparison_status != request.comparison_status
            or deterministic_evidence(result.evidence)
            != deterministic_evidence(request.evidence)
            or result.status != "pending"
        ):
            raise MCPResponseError("MCP_REVIEW_RESPONSE_MISMATCH")
        return result

    return await audited_mcp_call(
        database_path=path,
        workflow_run_id=workflow_run_id or str(uuid4()),
        server_name="tazama-clinical",
        tool_name="submit_review_request",
        arguments=arguments,
        operation=operation,
        timeout_seconds=5.0,
    )


async def attest_review_via_mcp(
    request: SubmitAttestation,
    database_path: str | Path,
    *,
    workflow_run_id: str | None = None,
) -> ReviewAttestation:
    """Record an asserted demo identity through the real MCP transport."""
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("The configured SQLite database does not exist")
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tazama.mcp.server"],
        env={
            **os.environ,
            "TAZAMA_DB_PATH": str(path),
            "TAZAMA_ENABLE_DEMO_ATTESTATION": "1",
        },
    )
    arguments = {"request": request.model_dump(mode="json")}

    async def operation() -> ReviewAttestation:
        async with (
            stdio_client(server) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            response = await session.call_tool(
                "record_demo_attestation", arguments=arguments
            )
        if response.isError:
            raise MCPToolError("MCP_REVIEW_ATTESTATION_FAILED")
        payload = response.structuredContent
        if payload is None:
            if not response.content or response.content[0].type != "text":
                raise MCPResponseError("MCP_REVIEW_ATTESTATION_RESPONSE_EMPTY")
            payload = json.loads(response.content[0].text)
        if isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        return ReviewAttestation.model_validate_json(json.dumps(payload))

    return await audited_mcp_call(
        database_path=path,
        workflow_run_id=workflow_run_id or str(uuid4()),
        server_name="tazama-clinical",
        tool_name="record_demo_attestation",
        arguments=arguments,
        operation=operation,
    )
