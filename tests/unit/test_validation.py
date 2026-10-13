import pytest
from pydantic import ValidationError

from triageguard.mcp.contracts import (
    PatientObservations,
    ValidateObservationsRequest,
)
from triageguard.mcp.validation import validate_observations


def test_missing_observations_are_preserved():
    request = ValidateObservationsRequest(
        case_id="SYN-001",
        observations=PatientObservations(
            heart_rate_bpm=90.0,
            temperature_c=37.0,
        ),
    )

    result = validate_observations(request)

    assert result.status == "pending_protocol"
    assert "respiratory_rate_bpm" in result.missing_fields
    assert "systolic_bp_mmhg" in result.missing_fields
    assert request.observations.heart_rate_bpm == 90.0


def test_no_observations_does_not_trigger_scoring():
    request = ValidateObservationsRequest(
        case_id="SYN-002",
        observations=PatientObservations(),
    )

    result = validate_observations(request)

    assert result.status == "pending_protocol"
    assert len(result.missing_fields) == 6


def test_unknown_observation_is_rejected():
    with pytest.raises(ValidationError):
        PatientObservations(unknown_measurement=123)


def test_unsupported_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        ValidateObservationsRequest(
            schema_version="2.0",
            case_id="SYN-003",
            observations=PatientObservations(),
        )


def test_no_priority_is_generated():
    request = ValidateObservationsRequest(
        case_id="SYN-004",
        observations=PatientObservations(heart_rate_bpm=90.0),
    )

    result = validate_observations(request)

    assert "priority" not in result.model_dump()
    assert result.status != "ready_for_scoring"
