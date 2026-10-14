from pydantic import BaseModel, ConfigDict, Field

from tazama.patients.models import ObservationRecord

NUMERIC_FIELDS = (
    "heart_rate_bpm",
    "respiratory_rate_bpm",
    "systolic_bp_mmhg",
    "temperature_c",
    "spo2_percent",
)


class NumericChange(BaseModel):
    previous: float
    current: float
    delta: float


class ObservationComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    previous_observation_id: str
    current_observation_id: str
    numeric_changes: dict[str, NumericChange] = Field(default_factory=dict)
    missing_comparisons: list[str] = Field(default_factory=list)
    consciousness_changed: bool | None = None


def compare_observations(
    previous: ObservationRecord,
    current: ObservationRecord,
) -> ObservationComparison:
    """Compare observations without making clinical judgments."""

    if previous.case_id != current.case_id:
        raise ValueError("Cannot compare different patients")

    if current.recorded_at <= previous.recorded_at:
        raise ValueError("Current observation must be newer")

    changes = {}
    missing = []

    for field in NUMERIC_FIELDS:
        old_value = getattr(previous.observations, field)
        new_value = getattr(current.observations, field)

        if old_value is None or new_value is None:
            missing.append(field)
            continue

        changes[field] = NumericChange(
            previous=old_value,
            current=new_value,
            delta=new_value - old_value,
        )

    old_consciousness = previous.observations.consciousness
    new_consciousness = current.observations.consciousness

    consciousness_changed = None

    if old_consciousness is not None and new_consciousness is not None:
        consciousness_changed = old_consciousness != new_consciousness

    return ObservationComparison(
        case_id=previous.case_id,
        previous_observation_id=previous.observation_id,
        current_observation_id=current.observation_id,
        numeric_changes=changes,
        missing_comparisons=missing,
        consciousness_changed=consciousness_changed,
    )
