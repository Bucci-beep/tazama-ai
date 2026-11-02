"""A stalled local model must never block or alter the review request."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from tazama.clinical.history import CompareHistoryResult
from tazama.clinical.priority import determine_priority
from tazama.mcp.contracts import PatientObservations
from tazama.orchestration.mcp_graph import build_mcp_triage_graph
from tazama.orchestration.mcp_time import TimeContext
from tazama.patients.models import ObservationRecord, PatientTimeline
from tazama.storage.reviews import ReviewRequest


def make_repository() -> Mock:
    timeline = PatientTimeline(case_id="CASE-TIMEOUT-001")
    for index in range(2):
        timeline.add_record(
            ObservationRecord(
                observation_id=f"OBS-{index + 1}",
                case_id="CASE-TIMEOUT-001",
                recorded_at=datetime(2026, 10, 14, 8, tzinfo=UTC)
                + timedelta(minutes=index * 10),
                observation_type="baseline" if index == 0 else "recheck",
                observations=PatientObservations(
                    heart_rate_bpm=float(80 + index * 10),
                    respiratory_rate_bpm=12.0,
                    systolic_bp_mmhg=120.0,
                    temperature_c=37.0,
                    consciousness="alert",
                    mobility="walking",
                    trauma=False,
                ),
            )
        )
    repository = Mock()
    repository.get_timeline.return_value = timeline
    return repository


async def fake_history(request):
    return CompareHistoryResult(case_id=request.case_id, status="differences_found")


async def fake_priority(request):
    return determine_priority(request.observations, request.signs)


async def fake_time():
    return TimeContext(
        timezone="UTC",
        datetime=datetime(2026, 10, 15, 6, 30, tzinfo=UTC),
        day_of_week="Thursday",
        is_dst=False,
    )


@pytest.mark.asyncio
async def test_stalled_model_times_out_and_review_is_still_submitted(monkeypatch):
    monkeypatch.setenv("TAZAMA_OLLAMA_TIMEOUT_SECONDS", "0.2")
    received = []

    async def review(request):
        received.append(request)
        return ReviewRequest(
            request_id="REVIEW-001",
            case_id=request.case_id,
            observation_id=request.observation_id,
            status="pending",
            created_at=datetime.now(UTC),
            comparison_status=request.comparison_status,
            evidence=request.evidence,
        )

    async def stalled_model(evidence):
        await asyncio.Event().wait()  # never responds
        return {}

    graph = build_mcp_triage_graph(
        make_repository(),
        fake_history,
        review,
        fake_priority,
        explanation_tool=stalled_model,
        time_tool=fake_time,
    )

    started = time.monotonic()
    result = await graph.ainvoke(
        {"case_id": "CASE-TIMEOUT-001", "status": "pending", "reason": None}
    )
    elapsed = time.monotonic() - started

    assert elapsed < 5
    assert result["status"] == "awaiting_clinician_review"
    assert result["review_submission_status"] == "persisted"
    assert result["explanation"] is None
    assert result["explanation_error"] == "OLLAMA_EXPLANATION_TIMEOUT"
    assert received[0].evidence["explanation"] is None
    assert received[0].evidence["explanation_error"] == "OLLAMA_EXPLANATION_TIMEOUT"
    assert received[0].evidence["priority_result"] is not None