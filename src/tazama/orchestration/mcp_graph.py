"""MCP-enabled LangGraph workflow with persisted clinician review requests."""

from collections.abc import Awaitable, Callable
from typing import Literal

from langgraph.graph import END, START, StateGraph

from tazama.clinical.history import CompareHistoryRequest, CompareHistoryResult
from tazama.orchestration.mcp_history import compare_history_via_mcp
from tazama.orchestration.mcp_review import submit_review_via_mcp
from tazama.orchestration.state import TriageWorkflowState
from tazama.patients.history_adapter import to_history_request
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRequest, SubmitReviewRequest

HistoryTool = Callable[
    [CompareHistoryRequest],
    Awaitable[CompareHistoryResult],
]

ReviewTool = Callable[
    [SubmitReviewRequest],
    Awaitable[ReviewRequest],
]


class MCPWorkflowState(TriageWorkflowState, total=False):
    comparison_status: str | None
    comparison_result: dict | None
    comparison_error: str | None
    review_submission_status: str | None
    review_request_id: str | None
    review_submission_error: str | None


def validate_input(state: MCPWorkflowState) -> dict:
    if not state["case_id"].strip():
        return {"status": "invalid_input", "reason": "CASE_ID_MISSING"}
    return {"status": "pending", "reason": None}


def route_input(state: MCPWorkflowState) -> Literal["load", "reject"]:
    return "reject" if state["status"] == "invalid_input" else "load"


def build_mcp_triage_graph(
    repository: ObservationRepository,
    history_tool: HistoryTool = compare_history_via_mcp,
    review_tool: ReviewTool | None = None,
):
    """Compile an async graph that confirms review persistence via MCP."""

    async def default_review_tool(request: SubmitReviewRequest) -> ReviewRequest:
        return await submit_review_via_mcp(
            request,
            repository.database.database_path,
        )

    submit_tool = review_tool if review_tool is not None else default_review_tool

    builder = StateGraph(MCPWorkflowState)

    async def load_and_compare(state: MCPWorkflowState) -> dict:
        case_id = state["case_id"]
        timeline = repository.get_timeline(case_id)
        latest = timeline.latest()

        metadata = {
            "observation_count": len(timeline.records),
            "has_baseline": timeline.baseline() is not None,
            "has_rechecks": len(timeline.records) > 1,
            "latest_observation_id": (
                latest.observation_id if latest is not None else None
            ),
        }

        if not timeline.records:
            return {
                **metadata,
                "comparison_status": "insufficient_history",
                "comparison_result": {
                    "case_id": case_id,
                    "status": "insufficient_history",
                    "changes": [],
                    "not_comparable": [],
                    "reason": "NO_OBSERVATIONS",
                },
                "comparison_error": None,
            }

        request = to_history_request(timeline)

        try:
            result = await history_tool(request)
        except Exception:  # noqa: BLE001
            # History-tool failure is not a reassuring comparison.
            return {
                **metadata,
                "comparison_status": "tool_unavailable",
                "comparison_result": None,
                "comparison_error": "MCP_HISTORY_TOOL_UNAVAILABLE",
            }

        if result.case_id != case_id:
            return {
                **metadata,
                "comparison_status": "tool_unavailable",
                "comparison_result": None,
                "comparison_error": "MCP_HISTORY_CASE_MISMATCH",
            }

        return {
            **metadata,
            "comparison_status": result.status,
            "comparison_result": result.model_dump(mode="json"),
            "comparison_error": None,
        }

    def route_observation(
        state: MCPWorkflowState,
    ) -> Literal["submit", "missing"]:
        return "submit" if state.get("latest_observation_id") else "missing"

    async def submit_review(state: MCPWorkflowState) -> dict:
        evidence = {
            "comparison_status": state["comparison_status"],
            "comparison_result": state.get("comparison_result"),
            "comparison_error": state.get("comparison_error"),
        }

        request = SubmitReviewRequest(
            case_id=state["case_id"],
            actor_id="SYSTEM-AGENT",
            observation_id=state["latest_observation_id"],
            comparison_status=state["comparison_status"],
            evidence=evidence,
        )

        try:
            result = await submit_tool(request)
            if (
                result.status != "pending"
                or result.case_id != request.case_id
                or result.observation_id != request.observation_id
                or result.comparison_status != request.comparison_status
                or result.evidence != request.evidence
                or not result.request_id
            ):
                raise ValueError("Review response does not match request")
        except Exception:  # noqa: BLE001
            # The write might have succeeded before transport failed.
            # Therefore this means unconfirmed, not necessarily absent.
            return {
                "review_submission_status": "unconfirmed",
                "review_request_id": None,
                "review_submission_error": "MCP_REVIEW_SUBMISSION_UNCONFIRMED",
            }

        return {
            "review_submission_status": "persisted",
            "review_request_id": result.request_id,
            "review_submission_error": None,
        }

    def route_submission(
        state: MCPWorkflowState,
    ) -> Literal["confirmed", "failed"]:
        return (
            "confirmed"
            if state.get("review_submission_status") == "persisted"
            else "failed"
        )

    def await_review(state: MCPWorkflowState) -> dict:
        return {
            "status": "awaiting_clinician_review",
            "reason": (
                "HISTORY_COMPARISON_UNAVAILABLE"
                if state.get("comparison_error")
                else None
            ),
        }

    def submission_failed(state: MCPWorkflowState) -> dict:
        return {
            "status": "review_submission_failed",
            "reason": "MCP_REVIEW_SUBMISSION_UNCONFIRMED",
        }

    def missing_observation(state: MCPWorkflowState) -> dict:
        return {
            "status": "observation_missing",
            "reason": "NO_OBSERVATIONS",
            "review_submission_status": "not_attempted",
            "review_request_id": None,
        }

    def reject_input(state: MCPWorkflowState) -> dict:
        return {
            "status": "invalid_input",
            "reason": state["reason"],
            "review_submission_status": "not_attempted",
            "review_request_id": None,
        }

    builder.add_node("validate_input", validate_input)
    builder.add_node("load_and_compare", load_and_compare)
    builder.add_node("submit_review", submit_review)
    builder.add_node("await_clinician_review", await_review)
    builder.add_node("submission_failed", submission_failed)
    builder.add_node("missing_observation", missing_observation)
    builder.add_node("reject_input", reject_input)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        route_input,
        {"load": "load_and_compare", "reject": "reject_input"},
    )
    builder.add_conditional_edges(
        "load_and_compare",
        route_observation,
        {"submit": "submit_review", "missing": "missing_observation"},
    )
    builder.add_conditional_edges(
        "submit_review",
        route_submission,
        {"confirmed": "await_clinician_review", "failed": "submission_failed"},
    )
    builder.add_edge("await_clinician_review", END)
    builder.add_edge("submission_failed", END)
    builder.add_edge("missing_observation", END)
    builder.add_edge("reject_input", END)

    return builder.compile()
