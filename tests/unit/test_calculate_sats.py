from tazama.clinical.scoring import (
    CalculateSATSRequest,
    ScoredSATSResult,
    UnavailableSATSResult,
    calculate_sats,
)
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


def request(**overrides):
    return CalculateSATSRequest(
        case_id="SYN-100",
        observations=PatientObservations(**{**NORMAL, **overrides}),
    )


def test_complete_observations_are_scored_with_evidence():
    result = calculate_sats(request())

    assert isinstance(result, ScoredSATSResult)
    assert result.tews_total == 0
    assert result.tews_priority == "routine"
    assert result.protocol_version == "2015-chart-1"
    assert result.band_rule_id == "TEWS/BAND/ROUTINE"
    assert len(result.parameter_scores) == 7
    assert all(item.rule_id.startswith("TEWS/") for item in result.parameter_scores)


def test_high_tews_is_emergency():
    result = calculate_sats(
        request(respiratory_rate_bpm=30.0, heart_rate_bpm=130.0, trauma=True)
    )

    assert isinstance(result, ScoredSATSResult)
    assert result.tews_total == 7
    assert result.tews_priority == "emergency"


def test_scored_result_states_its_scope_and_hands_to_a_nurse():
    result = calculate_sats(request())

    assert isinstance(result, ScoredSATSResult)
    assert result.scope == "tews_only"
    assert result.discriminators_applied is False
    assert result.next_action == "nurse_review"
    assert "nurse must check" in result.note


def test_missing_observation_is_unavailable_and_named():
    data = {**NORMAL}
    del data["heart_rate_bpm"]
    result = calculate_sats(
        CalculateSATSRequest(
            case_id="SYN-101",
            observations=PatientObservations(**data),
        )
    )

    assert isinstance(result, UnavailableSATSResult)
    assert result.priority is None
    assert "heart_rate_bpm" in result.reason


def test_value_between_chart_bands_is_unavailable():
    result = calculate_sats(request(respiratory_rate_bpm=14.5))

    assert isinstance(result, UnavailableSATSResult)
    assert result.priority is None
    assert "respiratory_rate_bpm" in result.reason


def test_unrecognised_consciousness_is_unavailable():
    result = calculate_sats(request(consciousness="sleepy"))

    assert isinstance(result, UnavailableSATSResult)
    assert "consciousness" in result.reason