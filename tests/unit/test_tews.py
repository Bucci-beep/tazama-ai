import pytest

from tazama.clinical.tews import load_protocol, score_tews
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


def obs(**overrides):
    return PatientObservations(**{**NORMAL, **overrides})


def test_normal_patient_scores_zero_and_routine():
    result = score_tews(obs())
    assert result.status == "scored"
    assert result.total == 0
    assert result.priority == "routine"
    assert result.band_rule_id == "TEWS/BAND/ROUTINE"
    assert result.protocol_version == "2015-chart-1"


def test_every_score_cites_a_rule_id():
    result = score_tews(obs())
    assert len(result.parameter_scores) == 7
    assert all(item.rule_id.startswith("TEWS/") for item in result.parameter_scores)


@pytest.mark.parametrize(
    "field, value, expected",
    [
        ("respiratory_rate_bpm", 8.0, 2),
        ("respiratory_rate_bpm", 9.0, 0),
        ("respiratory_rate_bpm", 14.0, 0),
        ("respiratory_rate_bpm", 15.0, 1),
        ("respiratory_rate_bpm", 20.0, 1),
        ("respiratory_rate_bpm", 21.0, 2),
        ("respiratory_rate_bpm", 29.0, 2),
        ("respiratory_rate_bpm", 30.0, 3),
        ("heart_rate_bpm", 40.0, 2),
        ("heart_rate_bpm", 41.0, 1),
        ("heart_rate_bpm", 50.0, 1),
        ("heart_rate_bpm", 51.0, 0),
        ("heart_rate_bpm", 100.0, 0),
        ("heart_rate_bpm", 101.0, 1),
        ("heart_rate_bpm", 110.0, 1),
        ("heart_rate_bpm", 111.0, 2),
        ("heart_rate_bpm", 129.0, 2),
        ("heart_rate_bpm", 130.0, 3),
        ("systolic_bp_mmhg", 70.0, 3),
        ("systolic_bp_mmhg", 71.0, 2),
        ("systolic_bp_mmhg", 80.0, 2),
        ("systolic_bp_mmhg", 81.0, 1),
        ("systolic_bp_mmhg", 100.0, 1),
        ("systolic_bp_mmhg", 101.0, 0),
        ("systolic_bp_mmhg", 199.0, 0),
        ("systolic_bp_mmhg", 200.0, 2),
        ("temperature_c", 34.9, 2),
        ("temperature_c", 35.0, 0),
        ("temperature_c", 38.4, 0),
        ("temperature_c", 38.5, 2),
        ("consciousness", "alert", 0),
        ("consciousness", "voice", 1),
        ("consciousness", "pain", 2),
        ("consciousness", "confused", 2),
        ("consciousness", "unresponsive", 3),
        ("mobility", "walking", 0),
        ("mobility", "with_help", 1),
        ("mobility", "stretcher_immobile", 2),
        ("trauma", True, 1),
        ("trauma", False, 0),
    ],
)
def test_chart_boundaries(field, value, expected):
    result = score_tews(obs(**{field: value}))
    assert result.status == "scored"
    assert result.total == expected


@pytest.mark.parametrize(
    "overrides, total, priority",
    [
        ({"respiratory_rate_bpm": 15.0, "heart_rate_bpm": 101.0}, 2, "routine"),
        ({"respiratory_rate_bpm": 21.0, "heart_rate_bpm": 101.0}, 3, "urgent"),
        (
            {"respiratory_rate_bpm": 21.0, "heart_rate_bpm": 111.0, "mobility": "with_help"},
            5,
            "very_urgent",
        ),
        (
            {"respiratory_rate_bpm": 30.0, "heart_rate_bpm": 130.0, "trauma": True},
            7,
            "emergency",
        ),
    ],
)
def test_total_maps_to_priority_band(overrides, total, priority):
    result = score_tews(obs(**overrides))
    assert result.total == total
    assert result.priority == priority


def test_missing_observation_abstains_and_is_not_imputed():
    data = {**NORMAL}
    del data["heart_rate_bpm"]
    result = score_tews(PatientObservations(**data))
    assert result.status == "abstained"
    assert result.total is None
    assert result.priority is None
    assert "heart_rate_bpm" in result.missing


def test_value_between_chart_bands_abstains():
    result = score_tews(obs(respiratory_rate_bpm=14.5))
    assert result.status == "abstained"
    assert result.priority is None
    assert result.unscorable[0].reason == "not_a_whole_number"


def test_unrecognised_category_abstains():
    result = score_tews(obs(consciousness="sleepy"))
    assert result.status == "abstained"
    assert result.unscorable[0].reason == "unrecognised_value"


def test_category_matching_ignores_case_and_spaces():
    result = score_tews(obs(consciousness=" Alert "))
    assert result.status == "scored"
    assert result.total == 0


def test_spo2_is_not_scored():
    low = score_tews(obs(spo2_percent=70.0))
    none = score_tews(obs())
    assert low.total == none.total == 0


def test_priority_bands_cover_every_total_exactly_once():
    protocol = load_protocol()
    for total in range(0, 25):
        hits = [
            band
            for band in protocol["bands"]
            if total >= band["min"] and ("max" not in band or total <= band["max"])
        ]
        assert len(hits) == 1, total