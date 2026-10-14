"""Read-only FastAPI service for persisted synthetic observations."""

import sqlite3

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict

from tazama.api.dependencies import ObservationRepositoryDependency
from tazama.patients.models import ObservationRecord


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "tazama-api"
    synthetic_data_only: bool = True
    clinical_use_permitted: bool = False


class ObservationTimelineResponse(BaseModel):
    """Chronological persisted observations without clinical interpretation."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    records: list[ObservationRecord]


app = FastAPI(
    title="Tazama Read-Only API",
    description=(
        "Read-only access to persisted synthetic research data. "
        "Not clinically validated or permitted for clinical use."
    ),
    version="1.0.0",
)


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report service status and the synthetic-only safety boundary."""
    return HealthResponse()


@app.get(
    "/api/v1/cases/{case_id}/observations",
    response_model=ObservationTimelineResponse,
    responses={
        404: {"description": "No persisted observations for the case"},
        503: {"description": "Database configuration or storage unavailable"},
    },
)
def get_case_observations(
    case_id: str,
    repository: ObservationRepositoryDependency,
) -> ObservationTimelineResponse:
    """Return stored observations; perform no scoring, inference, or writes."""
    try:
        timeline = repository.get_timeline(case_id)
    except (sqlite3.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Persisted observations are unavailable or invalid",
        ) from exc

    if not timeline.records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No observations found for case",
        )

    return ObservationTimelineResponse(case_id=case_id, records=timeline.records)
