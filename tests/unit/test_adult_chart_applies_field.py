"""The nurse-confirmed adult-chart applicability field (contract only).

This field has no effect on scoring yet. These tests cover its shape and its safe
default, including for records stored before the field existed.
"""

import pytest
from pydantic import ValidationError

from tazama.mcp.contracts import PatientObservations


def test_defaults_to_not_assessed():
    assert PatientObservations().adult_chart_applies == "not_assessed"


@pytest.mark.parametrize("value", ["yes", "no", "not_assessed"])
def test_accepts_only_the_three_states(value):
    assert PatientObservations(adult_chart_applies=value).adult_chart_applies == value


@pytest.mark.parametrize("value", ["YES", "maybe", "", True, False, 1, None])
def test_rejects_anything_else(value):
    with pytest.raises(ValidationError):
        PatientObservations(adult_chart_applies=value)


def test_stored_record_without_the_field_loads_as_not_assessed():
    legacy_json = (
        '{"heart_rate_bpm": 78.0, "respiratory_rate_bpm": 16.0, '
        '"systolic_bp_mmhg": 124.0, "temperature_c": 36.8, "spo2_percent": null, '
        '"consciousness": "alert", "mobility": "walking", "trauma": false}'
    )
    loaded = PatientObservations.model_validate_json(legacy_json)
    assert loaded.adult_chart_applies == "not_assessed"
    assert loaded.heart_rate_bpm == 78.0


def test_confirmed_value_survives_a_json_round_trip():
    original = PatientObservations(adult_chart_applies="yes", heart_rate_bpm=80)
    restored = PatientObservations.model_validate_json(original.model_dump_json())
    assert restored.adult_chart_applies == "yes"