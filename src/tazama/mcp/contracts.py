from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PatientObservations(BaseModel):
    """Synthetic observations; not a clinical validation decision."""

    model_config = ConfigDict(extra="forbid", strict=True)

    heart_rate_bpm: float | None = None
    respiratory_rate_bpm: float | None = None
    systolic_bp_mmhg: float | None = None
    temperature_c: float | None = None
    spo2_percent: float | None = None
    consciousness: str | None = None
    mobility: str | None = None  # walking | with_help | stretcher_immobile
    trauma: bool | None = None


class ValidateObservationsRequest(BaseModel):
    """Versioned input contract for observation validation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    observations: PatientObservations


class ValidationIssue(BaseModel):
    field: str
    code: str
    message: str


class ValidateObservationsResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    status: Literal["invalid", "pending_protocol", "ready_for_scoring"]
    missing_fields: list[str] = Field(default_factory=list)
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)