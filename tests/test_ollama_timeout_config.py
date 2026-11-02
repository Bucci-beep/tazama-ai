"""Ollama explanation deadlines must remain finite and positive."""

import math

import pytest

from tazama.orchestration.mcp_config import (
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    OLLAMA_TIMEOUT_ENV,
    ollama_timeout_seconds,
)


def test_ollama_timeout_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv(OLLAMA_TIMEOUT_ENV, raising=False)

    assert ollama_timeout_seconds() == DEFAULT_OLLAMA_TIMEOUT_SECONDS


def test_ollama_timeout_accepts_valid_override(monkeypatch):
    monkeypatch.setenv(OLLAMA_TIMEOUT_ENV, "0.2")

    assert ollama_timeout_seconds() == 0.2


@pytest.mark.parametrize(
    "invalid",
    ["", "abc", "0", "-3", "nan", "inf", "-inf"],
)
def test_ollama_timeout_rejects_invalid_values(monkeypatch, invalid):
    monkeypatch.setenv(OLLAMA_TIMEOUT_ENV, invalid)

    result = ollama_timeout_seconds()

    assert result == DEFAULT_OLLAMA_TIMEOUT_SECONDS
    assert math.isfinite(result)
    assert result > 0
