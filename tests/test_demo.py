"""End-to-end demonstration regression test."""

import pytest

from tazama.demo import run_demo


@pytest.mark.asyncio
async def test_synthetic_demo_persists_one_review_and_one_audit_event(tmp_path):
    result = await run_demo(tmp_path / "demo.sqlite3")

    assert result["synthetic"] is True
    assert result["observation_count"] == 2
    assert result["comparison_status"] == "differences_found"
    assert result["priority_result"]["status"] == "minimum_only"
    assert result["priority_result"]["priority"] is None
    assert result["priority_result"]["priority_at_least"] == "routine"
    assert result["workflow_status"] == "awaiting_clinician_review"
    assert result["review_submission_status"] == "persisted"
    assert result["review_request_id"] == result["retry_review_request_id"]
    assert result["pending_review_count"] == 1
    assert result["audit_event_count"] == 1
    assert result["audit_events"][0]["action"] == "review.requested"
    assert result["priority_changed"] is False
    assert result["clinician_attestation"] == {
        "action": "approved",
        "clinician_id": "DEMO-CLINICIAN-001",
        "identity_assurance": "asserted_demo_identity",
        "identity_note": (
            "Simulated clinician identity operated by this demonstration script; "
            "not a person or authenticated clinical user"
        ),
        "request_id": result["review_request_id"],
    }
