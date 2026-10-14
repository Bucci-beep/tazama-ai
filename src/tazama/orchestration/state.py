"""Typed workflow state for Tazama."""

from typing import Literal, TypedDict

WorkflowStatus = Literal[
    "pending",
    "awaiting_clinician_review",
    "invalid_input",
]


class TimelineFields(TypedDict, total=False):
    """Optional metadata retrieved from SQLite."""

    observation_count: int
    has_baseline: bool
    has_rechecks: bool
    latest_observation_id: str | None


class TriageWorkflowState(TimelineFields):
    """State shared between deterministic LangGraph nodes."""

    case_id: str
    status: WorkflowStatus
    reason: str | None
