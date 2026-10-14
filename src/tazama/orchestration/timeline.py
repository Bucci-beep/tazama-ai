"""Read-only SQLite timeline integration for LangGraph."""

from tazama.storage.observations import ObservationRepository


def load_timeline(
    case_id: str,
    repository: ObservationRepository,
) -> dict:
    """Load persisted observations without clinical interpretation."""
    timeline = repository.get_timeline(case_id)

    return {
        "observation_count": len(timeline.records),
        "has_baseline": timeline.baseline() is not None,
        "has_rechecks": len(timeline.records) > 1,
        "latest_observation_id": (
            timeline.latest().observation_id if timeline.latest() is not None else None
        ),
    }
