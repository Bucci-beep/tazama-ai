from tazama.clinical.priority import determine_priority, load_discriminators
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


def obs(**overrides):
    return PatientObservations(**{**NORMAL, **overrides})


def test_emergency_sign_needs_no_vital_signs():
    result = determine_priority(PatientObservations(), [EMERGENCY_SIGN])

    assert result.status == "complete"
    assert result.priority == "emergency"
    assert result.matched_sign_ids == [EMERGENCY_SIGN]
    assert result.tews.status == "abstained"


def test_no_signs_and_normal_vitals_is_routine():
    result = determine_priority(obs(), [])

    assert result.status == "complete"
    assert result.priority == "routine"


def test_urgent_sign_with_normal_vitals_is_urgent():
    result = determine_priority(obs(), [URGENT_SIGN])

    assert result.priority == "urgent"


def test_highest_of_sign_and_tews_wins_when_sign_is_higher():
    # TEWS 3 is urgent; the very urgent sign is higher.
    result = determine_priority(
        obs(respiratory_rate_bpm=21.0, heart_rate_bpm=101.0), [VERY_URGENT_SIGN]
    )

    assert result.tews.total == 3
    assert result.priority == "very_urgent"


def test_highest_of_sign_and_tews_wins_when_tews_is_higher():
    # TEWS 5 is very urgent; the urgent sign is lower.
    result = determine_priority(
        obs(respiratory_rate_bpm=21.0, heart_rate_bpm=111.0, mobility="with_help"),
        [URGENT_SIGN],
    )

    assert result.tews.total == 5
    assert result.priority == "very_urgent"


def test_tews_alone_can_make_an_emergency():
    result = determine_priority(
        obs(respiratory_rate_bpm=30.0, heart_rate_bpm=130.0, trauma=True), []
    )

    assert result.priority == "emergency"


def test_signs_not_assessed_gives_a_minimum_only():
    result = determine_priority(obs(), None)

    assert result.status == "minimum_only"
    assert result.priority is None
    assert result.priority_at_least == "routine"
    assert "not been assessed" in result.reasons[0]


def test_missing_vitals_with_no_signs_abstains():
    result = determine_priority(PatientObservations(), [])

    assert result.status == "abstained"
    assert result.priority is None
    assert result.priority_at_least is None


def test_missing_vitals_with_a_sign_gives_a_minimum_only():
    result = determine_priority(PatientObservations(), [VERY_URGENT_SIGN])

    assert result.status == "minimum_only"
    assert result.priority is None
    assert result.priority_at_least == "very_urgent"


def test_unknown_sign_id_abstains():
    result = determine_priority(obs(), ["DISC/NOT/A_REAL_SIGN"])

    assert result.status == "abstained"
    assert result.priority is None
    assert result.unknown_sign_ids == ["DISC/NOT/A_REAL_SIGN"]


def test_duplicate_sign_ids_are_counted_once():
    result = determine_priority(obs(), [URGENT_SIGN, URGENT_SIGN])

    assert result.matched_sign_ids == [URGENT_SIGN]


def test_sign_lists_match_the_chart_counts_and_ids_are_unique():
    data = load_discriminators()
    counts = {level["level"]: len(level["signs"]) for level in data["levels"]}
    ids = [sign["sign_id"] for level in data["levels"] for sign in level["signs"]]

    assert counts == {"emergency": 6, "very_urgent": 23, "urgent": 10}
    assert len(ids) == len(set(ids))


def test_every_sign_id_is_prefixed_with_its_level():
    data = load_discriminators()
    for level in data["levels"]:
        prefix = "DISC/" + level["level"].upper() + "/"
        assert all(sign["sign_id"].startswith(prefix) for sign in level["signs"])
