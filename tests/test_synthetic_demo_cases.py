"""Regression tests for synthetic-only Tazama demonstration cases."""

import json
from pathlib import Path

import pytest

from tazama.clinical.history import (
    CompareHistoryRequest,
    TimedObservation,
    compare_with_history,
)
from tazama.clinical.priority import determine_priority
from tazama.mcp.contracts import PatientObservations

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "demo" / "synthetic_cases_v1.json"
)

FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case",
    FIXTURES["cases"],
    ids=lambda case: case["case_id"],
)
def test_synthetic_demo_case(case):
    baseline = PatientObservations.model_validate(case["baseline"])
    recheck = PatientObservations.model_validate(case["recheck"])
    expected = case["expected"]

    comparison = compare_with_history(
        CompareHistoryRequest(
            case_id=case["case_id"],
            before=TimedObservation(
                obs_id="baseline",
                taken_utc="2026-10-15T09:00:00+00:00",
                observations=baseline,
            ),
            after=TimedObservation(
                obs_id="recheck",
                taken_utc="2026-10-15T09:30:00+00:00",
                observations=recheck,
            ),
        )
    )

    assert comparison.status == expected["comparison_status"]
    assert [change.field for change in comparison.changes] == expected["changed_fields"]
    assert comparison.not_comparable == expected["not_comparable"]

    unassessed = determine_priority(recheck, signs=None)
    assessed = determine_priority(recheck, signs=[])

    assert unassessed.tews.total == expected["tews_total"]
    assert unassessed.status == expected["unassessed_status"]
    assert unassessed.priority_at_least == expected["unassessed_priority_at_least"]

    assert assessed.status == expected["assessed_empty_status"]
    assert assessed.priority == expected["assessed_empty_priority"]

    if "missing_fields" in expected:
        assert unassessed.tews.missing == expected["missing_fields"]
        assert [issue.field for issue in unassessed.tews.unscorable] == expected[
            "unscorable_fields"
        ]
