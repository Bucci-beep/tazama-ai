"""HTTP API for persisted synthetic Tazama observations."""

import sqlite3
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Path, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from tazama.api.dependencies import ObservationRepositoryDependency
from tazama.mcp.contracts import PatientObservations
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


class CreateObservationRequest(BaseModel):
    """One synthetic observation to persist without running clinical logic."""

    model_config = ConfigDict(extra="forbid")
    observation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    recorded_at: AwareDatetime
    observation_type: Literal["baseline", "recheck"]
    observations: PatientObservations


CaseId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]


app = FastAPI(
    title="Tazama Research API",
    version="1.0.0",
    description=(
        "Local synthetic-data research API. Not clinically validated or for clinical use."
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
    case_id: CaseId,
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


@app.post(
    "/api/v1/cases/{case_id}/observations",
    response_model=ObservationRecord,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "Observation conflicts with the persisted timeline"},
        503: {"description": "Database configuration or storage unavailable"},
    },
)
def create_case_observation(
    case_id: CaseId,
    request: CreateObservationRequest,
    repository: ObservationRepositoryDependency,
) -> ObservationRecord:
    """Persist one synthetic observation without scoring or workflow execution."""
    record_data = request.model_dump(exclude={"observation_id"})
    if request.observation_id is not None:
        record_data["observation_id"] = request.observation_id

    record = ObservationRecord(case_id=case_id, **record_data)

    try:
        repository.save(record)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Observation conflicts with existing persisted data",
        ) from exc
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Persisted observations are unavailable",
        ) from exc

    return record
