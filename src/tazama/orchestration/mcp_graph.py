"""MCP-enabled LangGraph workflow with SQLite dependency injection."""

from collections.abc import Awaitable, Callable
from typing import Literal

from langgraph.graph import END, START, StateGraph

from tazama.clinical.history import CompareHistoryRequest, CompareHistoryResult
from tazama.orchestration.mcp_history import compare_history_via_mcp
from tazama.orchestration.state import TriageWorkflowState
from tazama.patients.history_adapter import to_history_request
from tazama.storage.observations import ObservationRepository

HistoryTool = Callable[
    [CompareHistoryRequest],
    Awaitable[CompareHistoryResult],
]


class MCPWorkflowState(TriageWorkflowState, total=False):
    comparison_status: str | None
    comparison_result: dict | None
    comparison_error: str | None


def validate_input(state: MCPWorkflowState) -> dict:
    if not state["case_id"].strip():
        return {"status": "invalid_input", "reason": "CASE_ID_MISSING"}
    return {"status": "pending", "reason": None}


def route_input(state: MCPWorkflowState) -> Literal["load", "reject"]:
    return "reject" if state["status"] == "invalid_input" else "load"


def build_mcp_triage_graph(
    repository: ObservationRepository,
    history_tool: HistoryTool = compare_history_via_mcp,
):
    """Compile an async graph using SQLite and the MCP history tool."""
    builder = StateGraph(MCPWorkflowState)

    async def load_and_compare(state: MCPWorkflowState) -> dict:
        case_id = state["case_id"]
        timeline = repository.get_timeline(case_id)
        metadata = load_timeline_metadata(timeline)

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
            # Fail closed: MCP failures must never appear reassuring.
            # This boundary intentionally handles unexpected tool failures.
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

    def load_timeline_metadata(timeline) -> dict:
        # Reuse the same fields returned by the existing SQLite loader.
        latest = timeline.latest()
        return {
            "observation_count": len(timeline.records),
            "has_baseline": timeline.baseline() is not None,
            "has_rechecks": len(timeline.records) > 1,
            "latest_observation_id": (
                latest.observation_id if latest is not None else None
            ),
        }

    def await_review(state: MCPWorkflowState) -> dict:
        return {
            "status": "awaiting_clinician_review",
            "reason": (
                "HISTORY_COMPARISON_UNAVAILABLE"
                if state.get("comparison_error")
                else None
            ),
        }

    def reject_input(state: MCPWorkflowState) -> dict:
        return {
            "status": "invalid_input",
            "reason": state["reason"],
        }

    builder.add_node("validate_input", validate_input)
    builder.add_node("load_and_compare", load_and_compare)
    builder.add_node("await_clinician_review", await_review)
    builder.add_node("reject_input", reject_input)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        route_input,
        {"load": "load_and_compare", "reject": "reject_input"},
    )
    builder.add_edge("load_and_compare", "await_clinician_review")
    builder.add_edge("await_clinician_review", END)
    builder.add_edge("reject_input", END)

    return builder.compile()
