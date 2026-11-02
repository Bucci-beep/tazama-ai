"""The MCP deadline is configurable but can never be removed."""

import pytest

from tazama.orchestration.mcp_config import (
    DEFAULT_MCP_TIMEOUT_SECONDS,
    MCP_TIMEOUT_ENV,
    mcp_timeout_seconds,
)


def test_default_deadline_when_not_configured(monkeypatch):
    monkeypatch.delenv(MCP_TIMEOUT_ENV, raising=False)
    assert mcp_timeout_seconds() == DEFAULT_MCP_TIMEOUT_SECONDS


def test_valid_override_is_used(monkeypatch):
    monkeypatch.setenv(MCP_TIMEOUT_ENV, "42.5")
    assert mcp_timeout_seconds() == 42.5


@pytest.mark.parametrize("bad", ["", "abc", "0", "-3", "nan", "inf", "-inf"])
def test_invalid_override_falls_back_to_default(monkeypatch, bad):
    monkeypatch.setenv(MCP_TIMEOUT_ENV, bad)
    assert mcp_timeout_seconds() == DEFAULT_MCP_TIMEOUT_SECONDS