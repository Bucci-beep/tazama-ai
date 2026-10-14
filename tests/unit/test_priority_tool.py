import asyncio

import pytest
from pydantic import ValidationError

from tazama.mcp.contracts import PatientObservations
from tazama.mcp.priority_contract import DeterminePriorityRequest
from tazama.mcp.server import mcp


def make_request(**overrides):
    return DeterminePriorityRequest(
        case_id="SYN-200",
        observations=PatientObservations(),
        **overrides,
    )


def test_signs_default_to_not_assessed():
    assert make_request().signs is None


def test_empty_signs_means_assessed_and_none_found():
    assert make_request(signs=[]).signs == []


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        make_request(queue_position=1)


def test_unsupported_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        make_request(schema_version="2.0")


def test_priority_tool_is_exposed_and_no_approval_tool_exists():
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert "determine_priority" in names
    # The model must have no way to record an approval.
    assert not any("approv" in name for name in names)
