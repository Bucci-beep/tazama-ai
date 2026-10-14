"""Reproducible synthetic end-to-end demonstration of Tazama."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from tazama.mcp.contracts import PatientObservations
from tazama.orchestration.mcp_graph import build_mcp_triage_graph
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRepository

CASE_ID = "SYNTHETIC-DEMO-001"


def seed_observations(repository: ObservationRepository) -> None:
    """Insert two explicitly synthetic readings, without clinical interpretation."""
    recorded_at = datetime(2026, 10, 14, 8, tzinfo=UTC)

    for observation_id, observation_type, timestamp, heart_rate in [
        ("SYNTHETIC-OBS-001", "baseline", recorded_at, 80.0),
        (
            "SYNTHETIC-OBS-002",
            "recheck",
            recorded_at + timedelta(minutes=15),
            100.0,
        ),
    ]:
        repository.save(
            ObservationRecord(
                observation_id=observation_id,
                case_id=CASE_ID,
                observation_type=observation_type,
                recorded_at=timestamp,
                observations=PatientObservations(heart_rate_bpm=heart_rate),
            )
        )


async def run_demo(database_path: Path) -> dict:
    """Run the real workflow twice and inspect its persisted records."""
    database = Database(database_path)
    database.initialize()

    observations = ObservationRepository(database)
    seed_observations(observations)

    graph = build_mcp_triage_graph(observations)

    initial_state = {
        "case_id": CASE_ID,
        "status": "pending",
        "reason": None,
    }

    first = await graph.ainvoke(initial_state)
    second = await graph.ainvoke(initial_state)

    reviews = ReviewRepository(database).get_pending()

    with database.connect() as connection:
        audit_events = connection.execute(
            """
            SELECT action, actor_id, request_id
            FROM review_request_events
            ORDER BY occurred_at, event_id
            """
        ).fetchall()

    summary = {
        "case_id": CASE_ID,
        "synthetic": True,
        "observation_count": first["observation_count"],
        "comparison_status": first["comparison_status"],
        "comparison_result": first["comparison_result"],
        "workflow_status": first["status"],
        "review_submission_status": first["review_submission_status"],
        "review_request_id": first["review_request_id"],
        "retry_review_request_id": second["review_request_id"],
        "retry_workflow_status": second["status"],
        "pending_review_count": len(reviews),
        "audit_event_count": len(audit_events),
        "audit_events": [
            {
                "action": action,
                "actor_id": actor_id,
                "request_id": request_id,
            }
            for action, actor_id, request_id in audit_events
        ],
        "priority_changed": False,
        "clinician_approval_performed": False,
    }

    if (
        summary["workflow_status"] != "awaiting_clinician_review"
        or summary["review_submission_status"] != "persisted"
        or summary["retry_workflow_status"] != "awaiting_clinician_review"
        or summary["review_request_id"] != summary["retry_review_request_id"]
        or len(reviews) != 1
        or len(audit_events) != 1
        or audit_events[0][0] != "review.requested"
    ):
        raise RuntimeError("Synthetic end-to-end demonstration failed")

    return summary


def main() -> None:
    """Use a temporary database that is removed after the demonstration."""
    with TemporaryDirectory(prefix="tazama-demo-") as directory:
        result = asyncio.run(run_demo(Path(directory) / "demo.sqlite3"))
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
