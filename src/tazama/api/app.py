"""Read-only HTTP API for persisted synthetic Tazama observations."""

import sqlite3
from typing import Literal

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict

from tazama.api.dependencies import ObservationRepositoryDependency
from tazama.patients.models import ObservationRecord


class HealthResponse(BaseModel):
    """Availability of the HTTP service, not clinical readiness."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]
    service: Literal["tazama-api"]
    environment: Literal["synthetic-research"]
    clinical_use_permitted: Literal[False]


class ObservationTimelineResponse(BaseModel):
    """Chronological persisted observations without clinical interpretation."""

    model_config = ConfigDict(extra="forbid")
    case_id: str
    records: list[ObservationRecord]


app = FastAPI(
    title="Tazama Research API",
    version="1.0.0",
    description=(
        "Read-only local research API. Not clinically validated. Synthetic data only."
    ),
)


@app.get("/api/v1/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Report HTTP service availability only."""
    return HealthResponse(
        status="ok",
        service="tazama-api",
        environment="synthetic-research",
        clinical_use_permitted=False,
    )


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
