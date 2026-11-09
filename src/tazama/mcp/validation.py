from tazama.mcp.contracts import (
    PatientObservations,
    ValidateObservationsRequest,
    ValidateObservationsResponse,
    ValidationIssue,
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

    warnings: list[ValidationIssue] = []
    if observations.adult_chart_applies != "yes":
        warnings.append(
            ValidationIssue(
                field="adult_chart_applies",
                code="ADULT_CHART_NOT_CONFIRMED",
                message=(
                    "The nurse has not confirmed that the adult SATS chart applies; "
                    "scoring will abstain."
                ),
            )
        )

    return ValidateObservationsResponse(
        case_id=request.case_id,
        status="pending_protocol",
        missing_fields=missing_fields,
        warnings=warnings,
    )