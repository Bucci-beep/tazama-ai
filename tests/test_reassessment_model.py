from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tazama.patients.reassessment import RecheckObligation


def test_recheck_obligation_defaults_to_scheduled():
    obligation = RecheckObligation(
        case_id="JOSEPH-001",
        due_at=datetime.now(UTC) + timedelta(minutes=30),
        policy_reference="DEMO-POLICY-001",
    )

    assert obligation.status == "scheduled"
    assert obligation.obligation_id


def test_recheck_obligation_requires_policy_reference():
    with pytest.raises(ValidationError):
        RecheckObligation(
            case_id="JOSEPH-001",
            due_at=datetime.now(UTC),
            policy_reference="",
        )


def test_recheck_obligation_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        RecheckObligation(
            case_id="JOSEPH-001",
            due_at=datetime(2026, 10, 13, 9, 0),
            policy_reference="DEMO-POLICY-001",
        )


def test_recheck_obligation_normalizes_timezone():
    from datetime import timezone

    offset = timezone(timedelta(hours=3))

    obligation = RecheckObligation(
        case_id="JOSEPH-001",
        due_at=datetime(2026, 10, 13, 9, 0, tzinfo=offset),
        policy_reference="DEMO-POLICY-001",
    )

    assert obligation.due_at.utcoffset() == timedelta(0)
