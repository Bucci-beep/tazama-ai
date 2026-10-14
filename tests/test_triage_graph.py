"""Tests for the initial LangGraph workflow."""

from tazama.orchestration.graph import build_triage_graph


def test_valid_case_requires_clinician_review():
    graph = build_triage_graph()

    result = graph.invoke(
        {
            "case_id": "CASE-001",
            "status": "pending",
            "reason": None,
        }
    )

    assert result["case_id"] == "CASE-001"
    assert result["status"] == "awaiting_clinician_review"
    assert result["reason"] is None


def test_empty_case_id_is_rejected():
    graph = build_triage_graph()

    result = graph.invoke(
        {
            "case_id": "",
            "status": "pending",
            "reason": None,
        }
    )

    assert result["status"] == "invalid_input"
    assert result["reason"] == "CASE_ID_MISSING"


def test_whitespace_only_case_id_is_rejected():
    graph = build_triage_graph()

    result = graph.invoke(
        {
            "case_id": "   ",
            "status": "pending",
            "reason": None,
        }
    )

    assert result["status"] == "invalid_input"
    assert result["reason"] == "CASE_ID_MISSING"


def test_graph_does_not_accept_existing_review_status_as_approval():
    graph = build_triage_graph()

    result = graph.invoke(
        {
            "case_id": "CASE-002",
            "status": "awaiting_clinician_review",
            "reason": None,
        }
    )

    assert result["status"] == "awaiting_clinician_review"
    assert "approved" not in result
