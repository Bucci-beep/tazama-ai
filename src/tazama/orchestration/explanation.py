"""Bounded open-weights task for selecting evidence explanations."""

import os
from collections.abc import Mapping

from ollama import AsyncClient
from pydantic import BaseModel, ConfigDict, Field


class ExplanationSelection(BaseModel):
    """Only identifiers are model-generated; clinical prose remains deterministic."""

    model_config = ConfigDict(extra="forbid", strict=True)
    selected_explanation_ids: list[str] = Field(min_length=1, max_length=4)


EXPLANATIONS = {
    "comparison_available": "Recorded observations were compared; differences are descriptive and do not prove deterioration.",
    "comparison_unavailable": "History comparison was unavailable and requires human review.",
    "priority_complete": "A deterministic priority proposal was computed from the recorded observations and nurse-assessed signs.",
    "priority_qualified": "The deterministic result is qualified because signs or observations are incomplete.",
    "priority_unavailable": "Deterministic priority evidence was unavailable; no priority was inferred.",
    "human_review_required": "The evidence requires clinician review and does not itself approve or change priority.",
}


def allowed_explanations(evidence: Mapping[str, object]) -> list[str]:
    allowed = ["human_review_required"]
    comparison_status = evidence.get("comparison_status")
    comparison_completed = (
        comparison_status in {"differences_found", "no_differences"}
        and not evidence.get("comparison_error")
    )
    allowed.append(
        "comparison_available"
        if comparison_completed
        else "comparison_unavailable"
    )
    priority_status = evidence.get("priority_status")
    if priority_status == "complete":
        allowed.append("priority_complete")
    elif priority_status in {"minimum_only", "abstained"}:
        allowed.append("priority_qualified")
    else:
        allowed.append("priority_unavailable")
    return allowed


async def explain_evidence_with_ollama(
    evidence: Mapping[str, object],
    *,
    model: str | None = None,
    client: AsyncClient | None = None,
) -> dict:
    """Use Ollama to select relevant pre-approved explanations."""
    allowed = allowed_explanations(evidence)
    chosen_model = model or os.environ.get("TAZAMA_OLLAMA_MODEL", "llama3.2:3b")
    ollama_client = client or AsyncClient()
    response = await ollama_client.chat(
        model=chosen_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Select the explanation IDs that best help a clinician navigate "
                    "the supplied structured evidence. Return only allowed IDs. Do not "
                    "calculate, diagnose, approve, reject, or infer missing findings."
                ),
            },
            {
                "role": "user",
                "content": f"Allowed IDs: {allowed}\nEvidence: {dict(evidence)}",
            },
        ],
        format=ExplanationSelection.model_json_schema(),
        options={"temperature": 0},
    )
    selection = ExplanationSelection.model_validate_json(response.message.content)
    if not set(selection.selected_explanation_ids) <= set(allowed):
        raise ValueError("OLLAMA_EXPLANATION_OUTSIDE_GROUNDED_CHOICES")
    if len(selection.selected_explanation_ids) != len(
        set(selection.selected_explanation_ids)
    ):
        raise ValueError("OLLAMA_EXPLANATION_DUPLICATE_SELECTION")
    return {
        "status": "generated",
        "model": chosen_model,
        "selected_explanation_ids": selection.selected_explanation_ids,
        "statements": [
            EXPLANATIONS[item] for item in selection.selected_explanation_ids
        ],
    }
