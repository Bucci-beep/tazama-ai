"""Tazama HTTP API.

Synthetic-data research environment only.
No clinical decision-making endpoints are exposed.
"""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Availability of the HTTP service, not clinical readiness."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: Literal["tazama-api"]
    environment: Literal["synthetic-research"]
    clinical_use_permitted: Literal[False]


app = FastAPI(
    title="Tazama Research API",
    version="0.1.0",
    description=("Local research API. Not clinically validated. Synthetic data only."),
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
