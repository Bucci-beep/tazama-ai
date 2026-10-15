"""Typed API service for the existing MCP reassessment workflow."""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from tazama.clinical.history import CompareHistoryRequest, CompareHistoryResult
from tazama.clinical.priority import PriorityResult
from tazama.mcp.priority_contract import DeterminePriorityRequest
from tazama.orchestration.mcp_graph import build_mcp_triage_graph
from tazama.orchestration.mcp_time import TimeContext
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRequest, SubmitReviewRequest

HistoryTool = Callable[[CompareHistoryRequest], Awaitable[CompareHistoryResult]]
PriorityTool = Callable[[DeterminePriorityRequest], Awaitable[PriorityResult]]
ReviewTool = Callable[[SubmitReviewRequest], Awaitable[ReviewRequest]]
TimeTool = Callable[[], Awaitable[TimeContext]]
ExplanationTool = Callable[[dict], Awaitable[dict]]


class ReassessmentNotFoundError(ValueError):
    """The requested case has no persisted observations."""


class ReassessmentRequest(BaseModel):
    """Explicit nurse sign-assessment state for reassessment."""

    model_config = ConfigDict(extra="forbid", strict=True)

    signs: list[str] | None = None


class ReassessmentResponse(BaseModel):
    """Structured result of a human-supervised synthetic reassessment."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    workflow_run_id: str
    status: Literal["awaiting_clinician_review", "review_submission_failed"]
    reason: str | None
    observation_count: int
    has_baseline: bool
    has_rechecks: bool
    latest_observation_id: str
    comparison_status: str
    comparison_result: CompareHistoryResult | None
    comparison_error: str | None
    priority_status: Literal[
        "complete", "minimum_only", "abstained", "tool_unavailable"
    ]
    priority_result: PriorityResult | None
    priority_error: str | None
    explanation: dict[str, Any] | None
    explanation_error: str | None
    review_request_id: str | None
    review_submission_status: Literal["persisted", "unconfirmed"]
    review_submission_error: str | None
    workflow_provenance: dict[str, Any]
    mcp_audit_errors: list[str]


class ReassessmentService:
    """Invoke the established graph without duplicating clinical behavior."""

    def __init__(
        self,
        repository: ObservationRepository,
        *,
        history_tool: HistoryTool | None = None,
        priority_tool: PriorityTool | None = None,
        review_tool: ReviewTool | None = None,
        time_tool: TimeTool | None = None,
        explanation_tool: ExplanationTool | None = None,
    ) -> None:
        self.repository = repository
        self.graph = build_mcp_triage_graph(
            repository,
            history_tool=history_tool,
            priority_tool=priority_tool,
            review_tool=review_tool,
            time_tool=time_tool,
            explanation_tool=explanation_tool,
        )

    async def reassess(
        self,
        case_id: str,
        signs: list[str] | None = None,
    ) -> ReassessmentResponse:
        if not self.repository.get_timeline(case_id).records:
            raise ReassessmentNotFoundError(case_id)
        result = await self.graph.ainvoke(
            {
                "case_id": case_id,
                "status": "pending",
                "reason": None,
                "signs": signs,
            }
        )
        return ReassessmentResponse.model_validate(
            {k: v for k, v in result.items() if k != "signs"}
        )
