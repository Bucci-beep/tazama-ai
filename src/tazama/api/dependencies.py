"""FastAPI dependencies for existing Tazama persistence."""

import os
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, status

from tazama.api.reassessment import ReassessmentService
from tazama.orchestration.explanation import explain_evidence_with_ollama
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.rechecks import RecheckRepository


def get_observation_repository() -> ObservationRepository:
    """Connect to the configured existing database without initializing it."""
    configured_path = os.environ.get("TAZAMA_DB_PATH")
    if not configured_path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TAZAMA_DB_PATH is not configured",
        )

    path = Path(configured_path).expanduser()
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configured Tazama database does not exist",
        )

    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
            connection.execute("SELECT 1 FROM observations LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configured Tazama database is unavailable or invalid",
        ) from exc

    return ObservationRepository(Database(path))


ObservationRepositoryDependency = Annotated[
    ObservationRepository,
    Depends(get_observation_repository),
]


def get_reassessment_service(
    repository: ObservationRepositoryDependency,
) -> ReassessmentService:
    """Build the workflow service; Ollama is opt-in for the HTTP process."""
    explanation_tool = (
        explain_evidence_with_ollama if os.environ.get("TAZAMA_OLLAMA_MODEL") else None
    )
    return ReassessmentService(repository, explanation_tool=explanation_tool)


ReassessmentServiceDependency = Annotated[
    ReassessmentService,
    Depends(get_reassessment_service),
]


def get_recheck_repository(
    repository: ObservationRepositoryDependency,
) -> RecheckRepository:
    """Reuse the validated database for reassessment obligations."""
    return RecheckRepository(repository.database)


RecheckRepositoryDependency = Annotated[
    RecheckRepository,
    Depends(get_recheck_repository),
]
