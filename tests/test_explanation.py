from types import SimpleNamespace

import pytest

from tazama.orchestration.explanation import (
    allowed_explanations,
    explain_evidence_with_ollama,
)


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.kwargs = None

    async def chat(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(message=SimpleNamespace(content=self.content))


@pytest.mark.asyncio
async def test_model_can_only_select_grounded_preapproved_statements():
    client = FakeClient(
        '{"selected_explanation_ids":["priority_qualified","human_review_required"]}'
    )
    result = await explain_evidence_with_ollama(
        {"comparison_error": None, "priority_status": "minimum_only"},
        model="test-model",
        client=client,
    )

    assert result["model"] == "test-model"
    assert result["selected_explanation_ids"] == [
        "priority_qualified",
        "human_review_required",
    ]
    assert result["statements"]
    assert all(text.endswith(".") for text in result["statements"])
    assert "tools" not in client.kwargs


@pytest.mark.asyncio
async def test_model_output_outside_grounded_choices_is_rejected():
    with pytest.raises(ValueError, match="OUTSIDE_GROUNDED_CHOICES"):
        await explain_evidence_with_ollama(
            {"comparison_error": None, "priority_status": "complete"},
            client=FakeClient('{"selected_explanation_ids":["priority_unavailable"]}'),
        )


@pytest.mark.parametrize(
    ("comparison_status", "comparison_error", "expected_id"),
    [
        ("differences_found", None, "comparison_available"),
        ("no_differences", None, "comparison_available"),
        ("insufficient_history", None, "comparison_unavailable"),
        ("untrusted_reading", None, "comparison_unavailable"),
        ("tool_unavailable", "MCP_TIMEOUT", "comparison_unavailable"),
        ("tool_unavailable", None, "comparison_unavailable"),
        ("differences_found", "MCP_ERROR", "comparison_unavailable"),
        ("no_differences", "MCP_ERROR", "comparison_unavailable"),
        (None, None, "comparison_unavailable"),
        ("unexpected_status", None, "comparison_unavailable"),
    ],
)
def test_comparison_explanation_status_matrix(
    comparison_status, comparison_error, expected_id
):
    allowed = allowed_explanations(
        {
            "comparison_status": comparison_status,
            "comparison_error": comparison_error,
            "priority_status": "complete",
        }
    )

    comparison_ids = {
        "comparison_available",
        "comparison_unavailable",
    }
    assert comparison_ids.intersection(allowed) == {expected_id}


@pytest.mark.asyncio
async def test_model_cannot_select_comparison_available_without_history():
    with pytest.raises(ValueError, match="OUTSIDE_GROUNDED_CHOICES"):
        await explain_evidence_with_ollama(
            {
                "comparison_status": "insufficient_history",
                "comparison_error": None,
                "priority_status": "complete",
            },
            client=FakeClient(
                '{"selected_explanation_ids":["comparison_available"]}'
            ),
        )


@pytest.mark.asyncio
async def test_duplicate_model_selections_are_rejected():
    with pytest.raises(ValueError, match="DUPLICATE_SELECTION"):
        await explain_evidence_with_ollama(
            {
                "comparison_status": "differences_found",
                "comparison_error": None,
                "priority_status": "complete",
            },
            client=FakeClient(
                '{"selected_explanation_ids":'
                '["comparison_available","comparison_available"]}'
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"selected_explanation_ids":[]}',
        '{"selected_explanation_ids":["priority_complete"],"extra":true}',
        '{"selected_explanation_ids":[123]}',
    ],
)
async def test_malformed_model_selections_are_rejected(content):
    with pytest.raises(ValueError):
        await explain_evidence_with_ollama(
            {
                "comparison_status": "differences_found",
                "comparison_error": None,
                "priority_status": "complete",
            },
            client=FakeClient(content),
        )
