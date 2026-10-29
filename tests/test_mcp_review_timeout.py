"""Timeout regression tests for Review MCP submission."""

import asyncio

import pytest

from tazama.orchestration import mcp_review
from tazama.storage.database import Database
from tazama.storage.mcp_audit import MCPToolCallRepository
from tazama.storage.reviews import ReviewRepository, SubmitReviewRequest


@pytest.mark.asyncio
async def test_hanging_review_mcp_call_times_out_and_is_audited(tmp_path, monkeypatch):
    database_path = tmp_path / "review-timeout.sqlite3"
    database = Database(database_path)
    database.initialize()

    reviews = ReviewRepository(database)
    reviews.initialize()

    request = SubmitReviewRequest(
        case_id="SYNTHETIC-001",
        actor_id="SYSTEM-AGENT",
        observation_id="OBS-001",
        comparison_status="insufficient_history",
        evidence={"reason": "Synthetic timeout test"},
    )

    class HangingStdio:
        async def __aenter__(self):
            await asyncio.Event().wait()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        mcp_review,
        "stdio_client",
        lambda server: HangingStdio(),
    )

    original_audited_call = mcp_review.audited_mcp_call

    async def short_deadline_call(**kwargs):
        assert kwargs["timeout_seconds"] == 5.0
        kwargs["timeout_seconds"] = 0.05
        return await original_audited_call(**kwargs)

    monkeypatch.setattr(
        mcp_review,
        "audited_mcp_call",
        short_deadline_call,
    )

    with pytest.raises(TimeoutError):
        await mcp_review.submit_review_via_mcp(
            request,
            database_path,
            workflow_run_id="RUN-REVIEW-TIMEOUT",
        )

    calls = MCPToolCallRepository(database).get_by_workflow_run("RUN-REVIEW-TIMEOUT")

    assert len(calls) == 1
    assert calls[0].tool_name == "submit_review_request"
    assert calls[0].status == "transport_error"
    assert calls[0].error["type"] == "TimeoutError"
    assert calls[0].output is None
    assert reviews.get_pending() == []
