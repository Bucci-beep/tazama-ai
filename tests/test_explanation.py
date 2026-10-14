from types import SimpleNamespace

import pytest

from tazama.orchestration.explanation import explain_evidence_with_ollama


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
