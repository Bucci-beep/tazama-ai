"""MCP stdio client for persistent clinician review submission."""

import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tazama.storage.reviews import ReviewRequest, SubmitReviewRequest


async def submit_review_via_mcp(
    request: SubmitReviewRequest,
    database_path: str | Path,
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

    async with (
        stdio_client(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        response = await session.call_tool(
            "submit_review_request",
            arguments={"request": request.model_dump(mode="json")},
        )

    if response.isError:
        raise RuntimeError("MCP_REVIEW_SUBMISSION_FAILED")

    payload = response.structuredContent

    if payload is None:
        if not response.content:
            raise RuntimeError("MCP_REVIEW_RESPONSE_EMPTY")

        first = response.content[0]

        if first.type != "text":
            raise RuntimeError("MCP_REVIEW_RESPONSE_NOT_TEXT")

        payload = json.loads(first.text)

    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]

    result = ReviewRequest.model_validate_json(json.dumps(payload))

    if (
        result.case_id != request.case_id
        or result.observation_id != request.observation_id
        or result.comparison_status != request.comparison_status
        or result.evidence != request.evidence
        or result.status != "pending"
    ):
        raise RuntimeError("MCP_REVIEW_RESPONSE_MISMATCH")

    return result
