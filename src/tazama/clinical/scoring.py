from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tazama.mcp.contracts import PatientObservations


class CalculateSATSRequest(BaseModel):
    """Versioned request for deterministic SATS calculation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    observations: PatientObservations


class UnavailableSATSResult(BaseModel):
    """Safe result when no verified scoring engine is available."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    status: Literal["unavailable"] = "unavailable"
    priority: None = None
    protocol_version: None = None
    reason: str = Field(min_length=1)
    next_action: Literal["human_clinical_assessment"] = "human_clinical_assessment"


def calculate_sats(
    request: CalculateSATSRequest,
) -> UnavailableSATSResult:
    """
    Return an explicit unavailable result.

    No SATS rules are implemented or simulated here.
    A verified deterministic engine must replace this adapter.
    """
    return UnavailableSATSResult(
        case_id=request.case_id,
        reason="Verified SATS scoring engine not installed",
    )
