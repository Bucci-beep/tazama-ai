"""Deadline configuration for MCP tool calls in the review workflow."""

import math
import os

DEFAULT_MCP_TIMEOUT_SECONDS = 15.0
MCP_TIMEOUT_ENV = "TAZAMA_MCP_TIMEOUT_SECONDS"


def mcp_timeout_seconds() -> float:
    """Return the MCP call deadline in seconds.

    Set TAZAMA_MCP_TIMEOUT_SECONDS to override the default. A missing, invalid,
    non-finite or non-positive value falls back to the default so that a bad
    setting can never remove the deadline.
    """
    raw = os.environ.get(MCP_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_MCP_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MCP_TIMEOUT_SECONDS
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_MCP_TIMEOUT_SECONDS
    return value


DEFAULT_OLLAMA_TIMEOUT_SECONDS = 30.0
OLLAMA_TIMEOUT_ENV = "TAZAMA_OLLAMA_TIMEOUT_SECONDS"


def ollama_timeout_seconds() -> float:
    """Return a finite, positive deadline for Ollama explanations.

    Invalid, non-finite, non-positive or missing configuration
    falls back to the default deadline.
    """
    raw = os.environ.get(OLLAMA_TIMEOUT_ENV)

    if raw is None:
        return DEFAULT_OLLAMA_TIMEOUT_SECONDS

    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_OLLAMA_TIMEOUT_SECONDS

    if not math.isfinite(value) or value <= 0:
        return DEFAULT_OLLAMA_TIMEOUT_SECONDS

    return value
