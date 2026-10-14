"""Minimal deterministic LangGraph workflow."""

from typing import Literal

from langgraph.graph import END, START, StateGraph

from tazama.orchestration.state import TriageWorkflowState


def validate_input(state: TriageWorkflowState) -> dict:
    """Validate workflow identity without clinical interpretation."""
    if not state["case_id"].strip():
        return {
            "status": "invalid_input",
            "reason": "CASE_ID_MISSING",
        }

    return {
        "status": "pending",
        "reason": None,
    }


def select_route(
    state: TriageWorkflowState,
) -> Literal["review", "reject"]:
    """Route exclusively on deterministic input-validation status."""
    if state["status"] == "invalid_input":
        return "reject"

    return "review"


def await_clinician_review(state: TriageWorkflowState) -> dict:
    """Record that human review is required; do not grant approval."""
    return {
        "status": "awaiting_clinician_review",
        "reason": None,
    }


def reject_input(state: TriageWorkflowState) -> dict:
    """Preserve the reason for invalid workflow input."""
    return {
        "status": "invalid_input",
        "reason": state["reason"],
    }


def build_triage_graph():
    """Compile the initial Tazama workflow."""
    builder = StateGraph(TriageWorkflowState)

    builder.add_node("validate_input", validate_input)
    builder.add_node("await_clinician_review", await_clinician_review)
    builder.add_node("reject_input", reject_input)

    builder.add_edge(START, "validate_input")

    builder.add_conditional_edges(
        "validate_input",
        select_route,
        {
            "review": "await_clinician_review",
            "reject": "reject_input",
        },
    )

    builder.add_edge("await_clinician_review", END)
    builder.add_edge("reject_input", END)

    return builder.compile()
