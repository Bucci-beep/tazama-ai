"""Local MCP server for deterministic Tazama tools."""

import os

from mcp.server.fastmcp import FastMCP

from tazama.clinical.history import (
    CompareHistoryRequest,
    CompareHistoryResult,
)
from tazama.clinical.history import (
    compare_with_history as compare_with_history_core,
)
from tazama.clinical.priority import (
    PriorityResult,
)
from tazama.clinical.priority import (
    determine_priority as determine_priority_core,
)
from tazama.clinical.scoring import (
    CalculateSATSRequest,
    ScoredSATSResult,
    UnavailableSATSResult,
)
from tazama.clinical.scoring import (
    calculate_sats as calculate_sats_core,
)
from tazama.mcp.contracts import (
    ValidateObservationsRequest,
    ValidateObservationsResponse,
)
from tazama.mcp.priority_contract import DeterminePriorityRequest
from tazama.mcp.validation import (
    validate_observations as validate_observations_core,
)
from tazama.storage.database import Database
from tazama.storage.reviews import (
    ReviewRepository,
    ReviewRequest,
    SubmitReviewRequest,
)

mcp = FastMCP("Tazama Clinical Tools")


@mcp.tool()
def validate_observations(
    request: ValidateObservationsRequest,
) -> ValidateObservationsResponse:
    """Report missing synthetic observations; do not assess clinical readiness."""
    return validate_observations_core(request)


@mcp.tool()
def calculate_sats(
    request: CalculateSATSRequest,
) -> ScoredSATSResult | UnavailableSATSResult:
    """Calculate the SATS TEWS from the protocol file, or return unavailable.

    Abstains when any observation is missing or off-chart. Covers the TEWS only; the
    chart's emergency, very urgent and urgent signs are not applied.
    """
    return calculate_sats_core(request)


@mcp.tool()
def compare_with_history(
    request: CompareHistoryRequest,
) -> CompareHistoryResult:
    """Report differences between earlier and new readings; not a clinical judgement."""
    return compare_with_history_core(request)


@mcp.tool()
def submit_review_request(request: SubmitReviewRequest) -> ReviewRequest:
    """Persist a review request; never approve or change clinical priority."""
    database_path = os.environ.get("TAZAMA_DB_PATH")

    if not database_path:
        raise ValueError("TAZAMA_DB_PATH is required for review submission")

    database = Database(database_path)
    repository = ReviewRepository(database)
    repository.initialize()
    return repository.submit(request)


@mcp.tool()
def determine_priority(
    request: DeterminePriorityRequest,
) -> PriorityResult:
    """Propose SATS priority from nurse-identified signs and TEWS.

    Signs are supplied by a nurse, not detected automatically.
    Missing or unscorable evidence prevents a definitive priority.
    The proposal requires clinician approval.
    """
    return determine_priority_core(request.observations, request.signs)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
