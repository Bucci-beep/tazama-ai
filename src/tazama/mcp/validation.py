from tazama.mcp.contracts import (
    PatientObservations,
    ValidateObservationsRequest,
    ValidateObservationsResponse,
)


def validate_observations(
    request: ValidateObservationsRequest,
) -> ValidateObservationsResponse:
    """
    Inspect supplied observations without inventing missing values.

    This is structural completeness reporting, not SATS validation.
    Clinical scoring remains blocked until protocol verification.
    """
    observations: PatientObservations = request.observations

    missing_fields = [
        field_name
        for field_name in type(observations).model_fields
        if getattr(observations, field_name) is None
    ]

    return ValidateObservationsResponse(
        case_id=request.case_id,
        status="pending_protocol",
        missing_fields=missing_fields,
    )
