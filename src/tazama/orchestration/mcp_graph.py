"""MCP-enabled LangGraph workflow with persisted clinician review requests."""

from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from tazama.clinical.history import CompareHistoryRequest, CompareHistoryResult
from tazama.clinical.priority import PriorityResult
from tazama.mcp.priority_contract import DeterminePriorityRequest
from tazama.orchestration.mcp_history import compare_history_via_mcp
from tazama.orchestration.mcp_priority import determine_priority_via_mcp
from tazama.orchestration.mcp_review import submit_review_via_mcp
from tazama.orchestration.mcp_time import TimeContext, get_current_utc_via_mcp
from tazama.orchestration.state import TriageWorkflowState
from tazama.patients.history_adapter import to_history_request
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import (
    ReviewRequest,
    SubmitReviewRequest,
    deterministic_evidence,
)

HistoryTool = Callable[
    [CompareHistoryRequest],
    Awaitable[CompareHistoryResult],
]

ReviewTool = Callable[
    [SubmitReviewRequest],
    Awaitable[ReviewRequest],
]
PriorityTool = Callable[[DeterminePriorityRequest], Awaitable[PriorityResult]]
ExplanationTool = Callable[[dict], Awaitable[dict]]
TimeTool = Callable[[], Awaitable[TimeContext]]


class MCPWorkflowState(TriageWorkflowState, total=False):
    workflow_run_id: str
    signs: list[str] | None
    comparison_status: str | None
    comparison_result: dict | None
    comparison_error: str | None
    priority_status: str | None
    priority_result: dict | None
    priority_error: str | None
    explanation: dict | None
    explanation_error: str | None
    workflow_provenance: dict | None
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
    history_tool: HistoryTool | None = None,
    review_tool: ReviewTool | None = None,
    priority_tool: PriorityTool | None = None,
    explanation_tool: ExplanationTool | None = None,
    time_tool: TimeTool | None = None,
):
    """Compile an async graph that confirms review persistence via MCP."""

    builder = StateGraph(MCPWorkflowState)

    async def capture_time_context(state: MCPWorkflowState) -> dict:
        """Capture nonclinical workflow provenance from a borrowed MCP server."""
        workflow_run_id = str(uuid4())
        try:
            context = (
                await time_tool()
                if time_tool is not None
                else await get_current_utc_via_mcp(
                    workflow_run_id=workflow_run_id,
                    database_path=repository.database.database_path,
                )
            )
            provenance = {
                "time": {
                    "status": "captured",
                    "server": "mcp-server-time",
                    "tool": "get_current_time",
                    "result": context.model_dump(mode="json"),
                }
            }
        except Exception:  # noqa: BLE001
            provenance = {
                "time": {
                    "status": "tool_unavailable",
                    "server": "mcp-server-time",
                    "tool": "get_current_time",
                    "error": "MCP_TIME_TOOL_UNAVAILABLE",
                }
            }
        return {"workflow_run_id": workflow_run_id, "workflow_provenance": provenance}

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
            result = (
                await history_tool(request)
                if history_tool is not None
                else await compare_history_via_mcp(
                    request,
                    workflow_run_id=state["workflow_run_id"],
                    database_path=repository.database.database_path,
                )
            )
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

    async def assess_priority(state: MCPWorkflowState) -> dict:
        timeline = repository.get_timeline(state["case_id"])
        latest = timeline.latest()
        if latest is None:
            return {
                "priority_status": "unavailable",
                "priority_result": None,
                "priority_error": "OBSERVATION_MISSING",
            }
        request = DeterminePriorityRequest(
            case_id=state["case_id"],
            observations=latest.observations,
            signs=state.get("signs"),
        )
        try:
            result = (
                await priority_tool(request)
                if priority_tool is not None
                else await determine_priority_via_mcp(
                    request,
                    workflow_run_id=state["workflow_run_id"],
                    database_path=repository.database.database_path,
                )
            )
        except Exception:  # noqa: BLE001
            return {
                "priority_status": "tool_unavailable",
                "priority_result": None,
                "priority_error": "MCP_PRIORITY_TOOL_UNAVAILABLE",
            }
        return {
            "priority_status": result.status,
            "priority_result": result.model_dump(mode="json"),
            "priority_error": None,
        }

    async def explain_evidence(state: MCPWorkflowState) -> dict:
        if explanation_tool is None:
            return {"explanation": None, "explanation_error": "NOT_CONFIGURED"}
        evidence = {
            "comparison_status": state.get("comparison_status"),
            "comparison_result": state.get("comparison_result"),
            "comparison_error": state.get("comparison_error"),
            "priority_status": state.get("priority_status"),
            "priority_result": state.get("priority_result"),
            "priority_error": state.get("priority_error"),
        }
        try:
            return {
                "explanation": await explanation_tool(evidence),
                "explanation_error": None,
            }
        except Exception:  # noqa: BLE001
            return {
                "explanation": None,
                "explanation_error": "OLLAMA_EXPLANATION_UNAVAILABLE",
            }

    async def submit_review(state: MCPWorkflowState) -> dict:
        evidence = {
            "comparison_status": state["comparison_status"],
            "comparison_result": state.get("comparison_result"),
            "comparison_error": state.get("comparison_error"),
            "priority_status": state.get("priority_status"),
            "priority_result": state.get("priority_result"),
            "priority_error": state.get("priority_error"),
            "signs_assessed": state.get("signs") is not None,
            "explanation": state.get("explanation"),
            "explanation_error": state.get("explanation_error"),
            "workflow_provenance": state.get("workflow_provenance"),
        }

        request = SubmitReviewRequest(
            case_id=state["case_id"],
            actor_id="SYSTEM-AGENT",
            observation_id=state["latest_observation_id"],
            comparison_status=state["comparison_status"],
            evidence=evidence,
        )

        try:
            result = (
                await review_tool(request)
                if review_tool is not None
                else await submit_review_via_mcp(
                    request,
                    repository.database.database_path,
                    workflow_run_id=state["workflow_run_id"],
                )
            )
            if (
                result.status != "pending"
                or result.case_id != request.case_id
                or result.observation_id != request.observation_id
                or result.comparison_status != request.comparison_status
                or deterministic_evidence(result.evidence)
                != deterministic_evidence(request.evidence)
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
    builder.add_node("capture_time_context", capture_time_context)
    builder.add_node("load_and_compare", load_and_compare)
    builder.add_node("assess_priority", assess_priority)
    builder.add_node("explain_evidence", explain_evidence)
    builder.add_node("submit_review", submit_review)
    builder.add_node("await_clinician_review", await_review)
    builder.add_node("submission_failed", submission_failed)
    builder.add_node("missing_observation", missing_observation)
    builder.add_node("reject_input", reject_input)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        route_input,
        {"load": "capture_time_context", "reject": "reject_input"},
    )
    builder.add_edge("capture_time_context", "load_and_compare")
    builder.add_conditional_edges(
        "load_and_compare",
        route_observation,
        {"submit": "assess_priority", "missing": "missing_observation"},
    )
    builder.add_edge("assess_priority", "explain_evidence")
    builder.add_edge("explain_evidence", "submit_review")
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
