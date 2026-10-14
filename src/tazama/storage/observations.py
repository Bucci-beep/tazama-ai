"""Persistent repository for patient observations."""

from datetime import UTC, datetime

from tazama.patients.models import ObservationRecord, PatientTimeline
from tazama.storage.database import Database


class ObservationRepository:
    """Store and retrieve observations without clinical interpretation."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, record: ObservationRecord) -> None:
        """Persist an observation while enforcing timeline invariants."""

        with self.database.connect() as connection:
            # Acquire the write lock before reading the timeline.
            # This prevents concurrent writers from passing the
            # same chronology checks.
            connection.execute("BEGIN IMMEDIATE")

            rows = connection.execute(
                """
                SELECT observation_id, case_id, observation_type,
                       recorded_at, observations_json
                FROM observations
                WHERE case_id = ?
                ORDER BY recorded_at ASC, observation_id ASC
                """,
                (record.case_id,),
            ).fetchall()

            timeline = PatientTimeline(case_id=record.case_id)

            for row in rows:
                existing = ObservationRecord(
                    observation_id=row[0],
                    case_id=row[1],
                    observation_type=row[2],
                    recorded_at=datetime.fromisoformat(row[3]),
                    observations=__import__("json").loads(row[4]),
                )
                timeline.add_record(existing)

            timeline.add_record(record)

            received_at = datetime.now(UTC).isoformat()

            connection.execute(
                """
                INSERT INTO observations (
                    observation_id,
                    case_id,
                    observation_type,
                    recorded_at,
                    received_at,
                    observations_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.observation_id,
                    record.case_id,
                    record.observation_type,
                    record.recorded_at.isoformat(),
                    received_at,
                    record.observations.model_dump_json(),
                ),
            )

    def get_timeline(self, case_id: str) -> PatientTimeline:
        """Reconstruct a patient's timeline from persistent records."""

        import json

        timeline = PatientTimeline(case_id=case_id)

        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT observation_id, case_id, observation_type,
                       recorded_at, observations_json
                FROM observations
                WHERE case_id = ?
                ORDER BY recorded_at ASC, observation_id ASC
                """,
                (case_id,),
            ).fetchall()

        for row in rows:
            timeline.add_record(
                ObservationRecord(
                    observation_id=row[0],
                    case_id=row[1],
                    observation_type=row[2],
                    recorded_at=datetime.fromisoformat(row[3]),
                    observations=json.loads(row[4]),
                )
            )

        return timeline
