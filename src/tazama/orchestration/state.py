"""Typed workflow state for Tazama."""

from typing import Literal, TypedDict

WorkflowStatus = Literal[
    "pending",
    "awaiting_clinician_review",
    "invalid_input",
]


class TriageWorkflowState(TypedDict):
    """State shared between deterministic LangGraph nodes."""

    case_id: str
    status: WorkflowStatus
    reason: str | None
