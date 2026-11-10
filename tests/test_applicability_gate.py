"""CLN02: the adult SATS chart is used only when a nurse confirms it applies.

Expected results (Cases D-H) were written from the clinical design before the gate
was implemented. Cases A-C are the locked fixtures in test_synthetic_demo_cases.py.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tazama.api.app import app
from tazama.api.dependencies import get_reassessment_service
from tazama.api.reassessment import ReassessmentService
from tazama.clinical.history import CompareHistoryResult
from tazama.clinical.priority import determine_priority
from tazama.clinical.scoring import (
    CalculateSATSRequest,
    ScoredSATSResult,
    UnavailableSATSResult,
    calculate_sats,
)
from tazama.clinical.tews import score_tews
from tazama.mcp.contracts import PatientObservations, ValidateObservationsRequest
from tazama.mcp.validation import validate_observations
from tazama.orchestration.mcp_time import TimeContext
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRequest

EMERGENCY_SIGN = "DISC/EMERGENCY/NOT_BREATHING"

# Case A recheck values: TEWS 1 when the adult chart applies.
CASE_A = {
    "heart_rate_bpm": 80,
    "respiratory_rate_bpm": 16,
    "systolic_bp_mmhg": 122,
    "temperature_c": 36.8,
    "consciousness": "alert",
    "mobility": "walking",
    "trauma": False,
}

# Case B recheck values: TEWS 5 when the adult chart applies.
CASE_B = {
    "heart_rate_bpm": 112,
    "respiratory_rate_bpm": 22,
    "systolic_bp_mmhg": 108,
    "temperature_c": 36.8,
    "consciousness": "alert",
    "mobility": "with_help",
    "trauma": False,
}

HUMAN_ASSESSMENT = "Human clinical assessment is required"
NOT_ROUTINE = "not a routine or low-risk result"


def obs(values: dict, applies: str | None) -> PatientObservations:
    if applies is None:  # field omitted, as in a record stored before CLN02
        return PatientObservations(**values)
    return PatientObservations(**values, adult_chart_applies=applies)


# (case, vitals, applicability, signs, expected reason fragment)
BLOCKED = [
    ("D", CASE_A, "not_assessed", [], "not confirmed"),
    ("E", CASE_A, "no", [], "does not apply"),
    ("F", CASE_A, None, [], "not confirmed"),
    ("G", CASE_B, "not_assessed", [EMERGENCY_SIGN], "not confirmed"),
    ("G-no", CASE_B, "no", [EMERGENCY_SIGN], "does not apply"),
]


@pytest.mark.parametrize(
    ("case", "values", "applies", "signs", "fragment"),
    BLOCKED,
    ids=[row[0] for row in BLOCKED],
)
def test_unconfirmed_applicability_abstains_with_no_priority(
    case, values, applies, signs, fragment
):
    observations = obs(values, applies)

    for assessed_signs in (signs, None):
        result = determine_priority(observations, assessed_signs)
        assert result.status == "abstained"
        assert result.priority is None
        assert result.priority_at_least is None
        assert result.matched_sign_ids == []
        assert result.tews.status == "abstained"
        assert result.tews.total is None
        assert result.tews.priority is None
        text = " ".join(result.reasons)
        assert fragment in text
        assert HUMAN_ASSESSMENT in text
        assert NOT_ROUTINE in text


@pytest.mark.parametrize(
    ("case", "values", "applies", "signs", "fragment"),
    BLOCKED,
    ids=[row[0] for row in BLOCKED],
)
def test_tews_is_not_calculated_when_applicability_is_unconfirmed(
    case, values, applies, signs, fragment
):
    tews = score_tews(obs(values, applies))

    assert tews.status == "abstained"
    assert tews.total is None
    assert tews.priority is None
    assert tews.parameter_scores == []
    assert [issue.field for issue in tews.unscorable] == ["adult_chart_applies"]
    assert fragment in tews.unscorable[0].detail


@pytest.mark.parametrize(
    ("case", "values", "applies", "signs", "fragment"),
    BLOCKED,
    ids=[row[0] for row in BLOCKED],
)
def test_calculate_sats_is_unavailable_when_applicability_is_unconfirmed(
    case, values, applies, signs, fragment
):
    result = calculate_sats(
        CalculateSATSRequest(case_id=f"SYN-{case}", observations=obs(values, applies))
    )

    assert isinstance(result, UnavailableSATSResult)
    assert result.priority is None
    assert result.next_action == "human_clinical_assessment"
    assert fragment in result.reason


def test_confirmed_applicability_scores_as_before():
    scored = calculate_sats(
        CalculateSATSRequest(case_id="SYN-A", observations=obs(CASE_A, "yes"))
    )
    assert isinstance(scored, ScoredSATSResult)
    assert scored.tews_total == 1

    priority = determine_priority(obs(CASE_B, "yes"), signs=[])
    assert priority.status == "complete"
    assert priority.priority == "very_urgent"


def test_emergency_sign_still_gives_emergency_when_applicability_is_confirmed():
    result = determine_priority(obs(CASE_B, "yes"), [EMERGENCY_SIGN])
    assert result.status == "complete"
    assert result.priority == "emergency"


def test_case_h_latest_observation_decides():
    baseline = obs(CASE_A, "yes")
    recheck = obs(CASE_A, "not_assessed")

    assert determine_priority(baseline, signs=[]).status == "complete"

    latest = determine_priority(recheck, signs=[])
    assert latest.status == "abstained"
    assert latest.priority is None


def test_validation_warns_when_applicability_is_not_confirmed():
    for applies in ("not_assessed", "no"):
        response = validate_observations(
            ValidateObservationsRequest(
                case_id="SYN-W", observations=obs(CASE_A, applies)
            )
        )
        warnings = [w for w in response.warnings if w.field == "adult_chart_applies"]
        assert len(warnings) == 1
        assert warnings[0].code == "ADULT_CHART_NOT_CONFIRMED"
        assert response.status != "ready_for_scoring"

    confirmed = validate_observations(
        ValidateObservationsRequest(case_id="SYN-W", observations=obs(CASE_A, "yes"))
    )
    assert [w for w in confirmed.warnings if w.field == "adult_chart_applies"] == []


def test_no_clinical_range_limits_were_added_for_applicability():
    """Structural checks only: odd but finite values are not rejected by CLN02."""
    result = determine_priority(
        obs({**CASE_A, "heart_rate_bpm": 100}, "not_assessed"), signs=[]
    )
    assert result.status == "abstained"  # because of applicability, not the value


def test_stored_legacy_record_without_the_field_abstains(tmp_path):
    database = Database(tmp_path / "legacy.sqlite3")
    database.initialize()
    repository = ObservationRepository(database)

    legacy_json = (
        '{"heart_rate_bpm": 80.0, "respiratory_rate_bpm": 16.0, '
        '"systolic_bp_mmhg": 122.0, "temperature_c": 36.8, "spo2_percent": null, '
        '"consciousness": "alert", "mobility": "walking", "trauma": false}'
    )
    recorded = datetime(2026, 11, 5, 9, tzinfo=UTC)
    with sqlite3.connect(database.database_path) as connection:
        connection.execute(
            """
            INSERT INTO observations (
                observation_id, case_id, observation_type,
                recorded_at, received_at, observations_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "LEGACY-1",
                "SYN-LEGACY",
                "baseline",
                recorded.isoformat(),
                (recorded + timedelta(seconds=1)).isoformat(),
                legacy_json,
            ),
        )

    timeline = repository.get_timeline("SYN-LEGACY")
    stored = timeline.records[0].observations
    assert stored.adult_chart_applies == "not_assessed"

    result = determine_priority(stored, signs=[])
    assert result.status == "abstained"
    assert result.priority is None

    with sqlite3.connect(database.database_path) as connection:
        row = connection.execute(
            "SELECT observations_json FROM observations WHERE observation_id = ?",
            ("LEGACY-1",),
        ).fetchone()
    assert row[0] == legacy_json  # nothing was rewritten


# --- Through the real API and workflow (initial triage path and reassessment path) ---


async def _history(request):
    return CompareHistoryResult(case_id=request.case_id, status="differences_found")


async def _priority(request):
    return determine_priority(request.observations, request.signs)


async def _review(request):
    return ReviewRequest(
        request_id="REVIEW-GATE-001",
        case_id=request.case_id,
        observation_id=request.observation_id,
        status="pending",
        created_at=datetime.now(UTC),
        comparison_status=request.comparison_status,
        evidence=request.evidence,
    )


async def _time():
    return TimeContext(
        timezone="UTC",
        datetime=datetime(2026, 11, 5, 9, tzinfo=UTC),
        day_of_week="Thursday",
        is_dst=False,
    )


def _reassess(tmp_path, observations_by_type, signs=None):
    database = Database(tmp_path / "gate.sqlite3")
    database.initialize()
    repository = ObservationRepository(database)
    start = datetime(2026, 11, 5, 8, tzinfo=UTC)
    for index, (kind, observations) in enumerate(observations_by_type):
        repository.save(
            ObservationRecord(
                observation_id=f"OBS-{index + 1}",
                case_id="SYN-GATE",
                observation_type=kind,
                recorded_at=start + timedelta(minutes=index * 10),
                observations=observations,
            )
        )
    service = ReassessmentService(
        repository,
        history_tool=_history,
        priority_tool=_priority,
        review_tool=_review,
        time_tool=_time,
    )
    app.dependency_overrides[get_reassessment_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/cases/SYN-GATE/reassess",
                json={"signs": signs} if signs is not None else None,
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


def test_workflow_initial_triage_abstains_when_unconfirmed(tmp_path):
    payload = _reassess(tmp_path, [("baseline", obs(CASE_B, "not_assessed"))], [])

    assert payload["priority_status"] == "abstained"
    assert payload["priority_result"]["priority"] is None
    assert payload["priority_result"]["priority_at_least"] is None
    assert payload["status"] == "awaiting_clinician_review"  # a human still reviews


def test_workflow_case_h_latest_observation_decides(tmp_path):
    payload = _reassess(
        tmp_path,
        [
            ("baseline", obs(CASE_A, "yes")),
            ("recheck", obs(CASE_A, "not_assessed")),
        ],
        [],
    )

    assert payload["latest_observation_id"] == "OBS-2"
    assert payload["priority_status"] == "abstained"
    assert payload["priority_result"]["priority"] is None


def test_workflow_confirmed_applicability_still_scores(tmp_path):
    payload = _reassess(
        tmp_path,
        [("baseline", obs(CASE_A, "yes")), ("recheck", obs(CASE_B, "yes"))],
        [],
    )

    assert payload["priority_status"] == "complete"
    assert payload["priority_result"]["priority"] == "very_urgent"