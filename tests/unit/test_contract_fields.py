import pytest
from pydantic import ValidationError

from tazama.mcp.contracts import PatientObservations


def test_new_fields_default_to_none():
    obs = PatientObservations()
    assert obs.mobility is None
    assert obs.trauma is None


def test_mobility_and_trauma_are_accepted():
    obs = PatientObservations(mobility="walking", trauma=False)
    assert obs.mobility == "walking"
    assert obs.trauma is False


def test_trauma_must_be_boolean():
    with pytest.raises(ValidationError):
        PatientObservations(trauma="yes")
