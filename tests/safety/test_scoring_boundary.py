import pytest
from pydantic import ValidationError

from tazama.clinical.scoring import (
    CalculateSATSRequest,
    UnavailableSATSResult,
    calculate_sats,
)
from tazama.mcp.contracts import PatientObservations


def make_request() -> CalculateSATSRequest:
    return CalculateSATSRequest(
        case_id="SYN-001",
        observations=PatientObservations(
            heart_rate_bpm=90.0,
            temperature_c=37.0,
        ),
    )


def test_unavailable_engine_does_not_assign_priority():
    result = calculate_sats(make_request())

    assert result.status == "unavailable"
    assert result.priority is None
    assert result.protocol_version is None


def test_unavailable_engine_requests_human_assessment():
    result = calculate_sats(make_request())

    assert result.next_action == "human_clinical_assessment"
    assert result.reason


def test_unavailable_result_cannot_contain_priority():
    with pytest.raises(ValidationError):
        UnavailableSATSResult(
            case_id="SYN-001",
            reason="Engine unavailable",
            priority="red",
        )


def test_unavailable_result_cannot_claim_success():
    with pytest.raises(ValidationError):
        UnavailableSATSResult(
            case_id="SYN-001",
            reason="Engine unavailable",
            status="success",
        )


def test_unavailable_engine_does_not_modify_observations():
    request = make_request()
    before = request.observations.model_dump()

    calculate_sats(request)

    assert request.observations.model_dump() == before


def test_empty_observations_cannot_generate_priority():
    request = CalculateSATSRequest(
        case_id="SYN-002",
        observations=PatientObservations(),
    )

    result = calculate_sats(request)

    assert result.status == "unavailable"
    assert result.priority is None
