from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tazama.clinical.tews import ParameterScore, TEWSResult, score_tews
from tazama.mcp.contracts import PatientObservations


class CalculateSATSRequest(BaseModel):
    """Versioned request for deterministic SATS calculation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    observations: PatientObservations


class UnavailableSATSResult(BaseModel):
    """Safe result when a SATS score cannot be calculated."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    status: Literal["unavailable"] = "unavailable"
    priority: None = None
    protocol_version: None = None
    reason: str = Field(min_length=1)
    next_action: Literal["human_clinical_assessment"] = "human_clinical_assessment"


class ScoredSATSResult(BaseModel):
    """TEWS result with the evidence behind it.

    This covers the TEWS only. The chart's emergency, very urgent and urgent sign lists
    are not applied here, so a nurse must still check them. The final SATS priority is the
    highest of the sign level and the TEWS band.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    status: Literal["scored"] = "scored"
    scope: Literal["tews_only"] = "tews_only"
    discriminators_applied: Literal[False] = False
    tews_total: int = Field(ge=0)
    tews_priority: Literal["routine", "urgent", "very_urgent", "emergency"]
    protocol_id: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    band_rule_id: str = Field(min_length=1)
    parameter_scores: list[ParameterScore]
    note: str = (
        "TEWS only. Emergency, very urgent and urgent signs are not applied; "
        "the nurse must check them. Final priority is the highest of the two."
    )
    next_action: Literal["nurse_review"] = "nurse_review"


def _unavailable_reason(tews: TEWSResult) -> str:
    parts: list[str] = []
    if tews.missing:
        parts.append("missing observations: " + ", ".join(tews.missing))
    if tews.unscorable:
        parts.append(
            "cannot be placed on the chart: "
            + "; ".join(f"{issue.field} ({issue.detail})" for issue in tews.unscorable)
        )
    return "TEWS not calculated; " + "; ".join(parts)


def calculate_sats(
    request: CalculateSATSRequest,
) -> ScoredSATSResult | UnavailableSATSResult:
    """
    Score the TEWS from the versioned protocol data file.

    If any observation is missing or cannot be placed on the chart, return an explicit
    unavailable result. Nothing is imputed, rounded or guessed.
    """
    tews = score_tews(request.observations)

    if tews.status != "scored" or tews.total is None or tews.priority is None:
        return UnavailableSATSResult(
            case_id=request.case_id,
            reason=_unavailable_reason(tews),
        )

    return ScoredSATSResult(
        case_id=request.case_id,
        tews_total=tews.total,
        tews_priority=tews.priority,
        protocol_id=tews.protocol_id,
        protocol_version=tews.protocol_version,
        band_rule_id=tews.band_rule_id or "",
        parameter_scores=tews.parameter_scores,
    )