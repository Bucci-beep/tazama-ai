from datetime import UTC, datetime, timedelta

import pytest

from tazama.mcp.contracts import PatientObservations
from tazama.patients.comparison import compare_observations
from tazama.patients.models import ObservationRecord, PatientTimeline

BASE_TIME = datetime(2026, 10, 13, 8, 15, tzinfo=UTC)


def make_record(
    minutes: int,
    observation_type: str,
    respiratory_rate: float = 18.0,
    spo2: float = 98.0,
) -> ObservationRecord:
    return ObservationRecord(
        case_id="JOSEPH-001",
        recorded_at=BASE_TIME + timedelta(minutes=minutes),
        observation_type=observation_type,
        observations=PatientObservations(
            respiratory_rate_bpm=respiratory_rate,
            spo2_percent=spo2,
        ),
    )


def test_baseline_and_recheck():
    timeline = PatientTimeline(case_id="JOSEPH-001")

    baseline = make_record(0, "baseline")
    recheck = make_record(30, "recheck")

    timeline.add_record(baseline)
    timeline.add_record(recheck)

    assert len(timeline.records) == 2
    assert timeline.baseline() == baseline
    assert timeline.latest() == recheck


def test_recheck_cannot_be_first():
    timeline = PatientTimeline(case_id="JOSEPH-001")

    with pytest.raises(ValueError):
        timeline.add_record(make_record(30, "recheck"))


def test_out_of_order_observation_rejected():
    timeline = PatientTimeline(case_id="JOSEPH-001")

    timeline.add_record(make_record(0, "baseline"))
    timeline.add_record(make_record(30, "recheck"))

    with pytest.raises(ValueError):
        timeline.add_record(make_record(15, "recheck"))


def test_duplicate_observation_rejected():
    timeline = PatientTimeline(case_id="JOSEPH-001")
    baseline = make_record(0, "baseline")

    timeline.add_record(baseline)

    with pytest.raises(ValueError):
        timeline.add_record(baseline)


def test_comparison_calculates_changes():
    baseline = make_record(0, "baseline", respiratory_rate=18.0, spo2=98.0)
    recheck = make_record(30, "recheck", respiratory_rate=26.0, spo2=93.0)

    result = compare_observations(baseline, recheck)

    assert result.numeric_changes["respiratory_rate_bpm"].delta == 8.0
    assert result.numeric_changes["spo2_percent"].delta == -5.0


def test_missing_values_not_imputed():
    baseline = make_record(0, "baseline")

    recheck = ObservationRecord(
        case_id="JOSEPH-001",
        recorded_at=BASE_TIME + timedelta(minutes=30),
        observation_type="recheck",
        observations=PatientObservations(
            respiratory_rate_bpm=26.0,
        ),
    )

    result = compare_observations(baseline, recheck)

    assert "spo2_percent" in result.missing_comparisons
    assert "spo2_percent" not in result.numeric_changes
