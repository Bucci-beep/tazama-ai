"""Evaluation cases for the deterministic triage layer.

Each case is synthetic. Expected outcomes come from the Adult SATS chart rules, written
down before running the code. One case (F01) is a known failure that is deliberately left
unfixed; it is marked as an expected failure so the suite stays green and the gap stays
visible. See EVALS.md.
"""

from dataclasses import dataclass

import pytest

from tazama.clinical.priority import determine_priority
from tazama.mcp.contracts import PatientObservations

NORMAL = {
    "heart_rate_bpm": 80.0,
    "respiratory_rate_bpm": 12.0,
    "systolic_bp_mmhg": 120.0,
    "temperature_c": 37.0,
    "consciousness": "alert",
    "mobility": "walking",
    "trauma": False,
}

EMERGENCY_SIGN = "DISC/EMERGENCY/NOT_BREATHING"
VERY_URGENT_SIGN = "DISC/VERY_URGENT/CHEST_PAIN"
URGENT_SIGN = "DISC/URGENT/MODERATE_PAIN"


def vitals(**overrides):
    return {**NORMAL, **overrides}


@dataclass(frozen=True)
class Case:
    case_id: str
    summary: str
    observations: dict
    signs: list[str] | None
    expected_status: str
    expected_priority: str | None = None
    expected_at_least: str | None = None


CASES = [
    Case("E01", "Normal vitals, no signs", vitals(), [], "complete", "routine"),
    Case(
        "E02",
        "Emergency sign with no vitals taken",
        {},
        [EMERGENCY_SIGN],
        "complete",
        "emergency",
    ),
    Case(
        "E03",
        "Chest pain ticked, normal vitals",
        vitals(),
        [VERY_URGENT_SIGN],
        "complete",
        "very_urgent",
    ),
    Case(
        "E04",
        "Moderate pain ticked, normal vitals",
        vitals(),
        [URGENT_SIGN],
        "complete",
        "urgent",
    ),
    Case(
        "E05",
        "TEWS 3 (RR 21, HR 101), no signs",
        vitals(respiratory_rate_bpm=21.0, heart_rate_bpm=101.0),
        [],
        "complete",
        "urgent",
    ),
    Case(
        "E06",
        "TEWS 5 (RR 21, HR 111, with help), no signs",
        vitals(respiratory_rate_bpm=21.0, heart_rate_bpm=111.0, mobility="with_help"),
        [],
        "complete",
        "very_urgent",
    ),
    Case(
        "E07",
        "TEWS 7 (RR 30, HR 130, trauma), no signs",
        vitals(respiratory_rate_bpm=30.0, heart_rate_bpm=130.0, trauma=True),
        [],
        "complete",
        "emergency",
    ),
    Case(
        "E08",
        "Urgent sign but TEWS 5: the higher band wins",
        vitals(respiratory_rate_bpm=21.0, heart_rate_bpm=111.0, mobility="with_help"),
        [URGENT_SIGN],
        "complete",
        "very_urgent",
    ),
    Case(
        "E09",
        "Heart rate missing: abstain, never impute",
        {k: v for k, v in NORMAL.items() if k != "heart_rate_bpm"},
        [],
        "abstained",
    ),
    Case(
        "E10",
        "Respiratory rate 14.5 sits between chart bands: abstain",
        vitals(respiratory_rate_bpm=14.5),
        [],
        "abstained",
    ),
    Case(
        "E11",
        "Unknown sign id: abstain, never guess",
        vitals(),
        ["DISC/NOT/A_REAL_SIGN"],
        "abstained",
    ),
    Case(
        "E12",
        "Signs not assessed yet: minimum only, no final priority",
        vitals(),
        None,
        "minimum_only",
        expected_at_least="routine",
    ),
    Case(
        "E13",
        "Temperature 38.4 is still in band (RR 15 scores 1): routine",
        vitals(temperature_c=38.4, respiratory_rate_bpm=15.0),
        [],
        "complete",
        "routine",
    ),
    Case(
        "E14",
        "Temperature 38.5 is over band (RR 15 scores 1, temp 2): urgent",
        vitals(temperature_c=38.5, respiratory_rate_bpm=15.0),
        [],
        "complete",
        "urgent",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.case_id for case in CASES])
def test_eval_case(case):
    result = determine_priority(PatientObservations(**case.observations), case.signs)

    assert result.status == case.expected_status
    assert result.priority == case.expected_priority
    assert result.priority_at_least == case.expected_at_least

    # Safety invariant on every case: no final priority unless the result is complete.
    if result.status != "complete":
        assert result.priority is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known limitation, left unfixed on purpose: Tazama only combines the signs a nurse "
        "ticks. If the nurse omits a sign that is really present, it under-triages. "
        "See EVALS.md, failure F01."
    ),
)
def test_F01_omitted_sign_is_not_detected():
    # Ground truth: the patient has chest pain (a very urgent sign), vitals are normal.
    # The nurse did not tick it, so the system sees no signs.
    nurse_ticked: list[str] = []

    result = determine_priority(PatientObservations(**vitals()), nurse_ticked)

    assert result.priority == "very_urgent"