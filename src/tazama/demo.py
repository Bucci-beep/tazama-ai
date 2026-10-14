"""Reproducible synthetic end-to-end demonstration of Tazama."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from tazama.mcp.contracts import PatientObservations
from tazama.orchestration.explanation import explain_evidence_with_ollama
from tazama.orchestration.mcp_graph import build_mcp_triage_graph
from tazama.orchestration.mcp_review import attest_review_via_mcp
from tazama.patients.models import ObservationRecord
from tazama.storage.database import Database
from tazama.storage.observations import ObservationRepository
from tazama.storage.reviews import ReviewRepository, SubmitAttestation

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
                observations=PatientObservations(
                    heart_rate_bpm=heart_rate,
                    respiratory_rate_bpm=12.0,
                    systolic_bp_mmhg=120.0,
                    temperature_c=37.0,
                    consciousness="alert",
                    mobility="walking",
                    trauma=False,
                ),
            )
        )


async def run_demo(database_path: Path, explanation_tool=None) -> dict:
    """Run the real workflow twice and inspect its persisted records."""
    database = Database(database_path)
    database.initialize()

    observations = ObservationRepository(database)
    seed_observations(observations)

    graph = build_mcp_triage_graph(observations, explanation_tool=explanation_tool)

    initial_state = {
        "case_id": CASE_ID,
        "status": "pending",
        "reason": None,
    }

    first = await graph.ainvoke(initial_state)
    second = await graph.ainvoke(initial_state)

    review_repository = ReviewRepository(database)
    reviews = review_repository.get_pending()
    attestation = await attest_review_via_mcp(
        SubmitAttestation(
            request_id=first["review_request_id"],
            clinician_id="DEMO-CLINICIAN-001",
            action="approved",
        ),
        database_path,
    )

    with database.connect() as connection:
        audit_events = connection.execute(
            """
            SELECT action, actor_id, request_id
            FROM review_request_events
            ORDER BY occurred_at, event_id
            """
        ).fetchall()
        persisted_priority = json.loads(
            connection.execute(
                "SELECT evidence_json FROM review_requests WHERE request_id = ?",
                (first["review_request_id"],),
            ).fetchone()[0]
        )["priority_result"]

    summary = {
        "case_id": CASE_ID,
        "synthetic": True,
        "observation_count": first["observation_count"],
        "comparison_status": first["comparison_status"],
        "comparison_result": first["comparison_result"],
        "priority_result": persisted_priority,
        "explanation": first["explanation"],
        "explanation_error": first["explanation_error"],
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
        "priority_change_basis": "No priority mutation operation exists",
        "clinician_attestation": {
            "action": attestation.action,
            "clinician_id": attestation.clinician_id,
            "identity_assurance": attestation.identity_assurance,
            "identity_note": (
                "Simulated clinician identity operated by this demonstration script; "
                "not a person or authenticated clinical user"
            ),
            "request_id": attestation.request_id,
        },
    }

    if (
        summary["workflow_status"] != "awaiting_clinician_review"
        or summary["review_submission_status"] != "persisted"
        or summary["retry_workflow_status"] != "awaiting_clinician_review"
        or summary["review_request_id"] != summary["retry_review_request_id"]
        or len(reviews) != 1
        or len(audit_events) != 1
        or audit_events[0][0] != "review.requested"
        or attestation.request_id != first["review_request_id"]
    ):
        raise RuntimeError("Synthetic end-to-end demonstration failed")

    return summary


def main() -> None:
    """Use a temporary database that is removed after the demonstration."""
    with TemporaryDirectory(prefix="tazama-demo-") as directory:
        result = asyncio.run(
            run_demo(
                Path(directory) / "demo.sqlite3",
                explanation_tool=explain_evidence_with_ollama,
            )
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
