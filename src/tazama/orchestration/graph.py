"""Deterministic LangGraph workflow with optional SQLite timeline loading."""

from typing import Literal

from langgraph.graph import END, START, StateGraph

from tazama.orchestration.state import TriageWorkflowState
from tazama.orchestration.timeline import load_timeline
from tazama.storage.observations import ObservationRepository


def validate_input(state: TriageWorkflowState) -> dict:
    """Validate case identity without clinical interpretation."""
    if not state["case_id"].strip():
        return {"status": "invalid_input", "reason": "CASE_ID_MISSING"}
    return {"status": "pending", "reason": None}


def select_route(state: TriageWorkflowState) -> Literal["review", "reject"]:
    """Route solely on deterministic input validation."""
    return "reject" if state["status"] == "invalid_input" else "review"


def await_clinician_review(state: TriageWorkflowState) -> dict:
    """Mark workflow for review, without granting approval."""
    return {"status": "awaiting_clinician_review", "reason": None}


def reject_input(state: TriageWorkflowState) -> dict:
    """Preserve invalid-input status and reason."""
    return {"status": "invalid_input", "reason": state["reason"]}


def build_triage_graph(
    repository: ObservationRepository | None = None,
):
    """Compile the graph with an optional injected SQLite repository."""
    builder = StateGraph(TriageWorkflowState)

    builder.add_node("validate_input", validate_input)
    builder.add_node("await_clinician_review", await_clinician_review)
    builder.add_node("reject_input", reject_input)

    if repository is not None:

        def load_patient_timeline(state: TriageWorkflowState) -> dict:
            """Load persisted history without clinical interpretation."""
            return load_timeline(state["case_id"], repository)

        builder.add_node("load_patient_timeline", load_patient_timeline)

    builder.add_edge(START, "validate_input")

    if repository is None:
        review_entry = "await_clinician_review"
    else:
        review_entry = "load_patient_timeline"
        builder.add_edge("load_patient_timeline", "await_clinician_review")

    builder.add_conditional_edges(
        "validate_input",
        select_route,
        {
            "review": review_entry,
            "reject": "reject_input",
        },
    )

    builder.add_edge("await_clinician_review", END)
    builder.add_edge("reject_input", END)

    return builder.compile()
