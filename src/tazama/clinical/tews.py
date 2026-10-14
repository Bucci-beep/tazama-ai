"""Deterministic SATS adult TEWS scoring.

All clinical thresholds are read from the versioned data file under data/protocol/.
No threshold lives in this module. If any required observation is missing or cannot be
placed in a band on the chart, the result is "abstained": no total, no priority.
Nothing is rounded, guessed or filled in.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tazama.mcp.contracts import PatientObservations

DEFAULT_PROTOCOL_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "protocol" / "tews_adult.json"
)


class ParameterScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    value: bool | float | str
    score: int
    rule_id: str


class UnscorableIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    reason: Literal[
        "not_a_whole_number",
        "not_a_finite_number",
        "no_matching_band",
        "unrecognised_value",
    ]
    detail: str


class TEWSResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["scored", "abstained"]
    protocol_id: str
    protocol_version: str
    total: int | None = None
    priority: str | None = None
    band_rule_id: str | None = None
    parameter_scores: list[ParameterScore] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unscorable: list[UnscorableIssue] = Field(default_factory=list)


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> str:
    return Path(path_str).read_text(encoding="utf-8")


def load_protocol(path: Path | None = None) -> dict[str, Any]:
    """Read the TEWS data file. Returns a fresh dict each call."""
    target = Path(path) if path is not None else DEFAULT_PROTOCOL_PATH
    return json.loads(_load_cached(str(target)))


def _in_band(value: float, band: dict[str, Any]) -> bool:
    if "min" in band and value < band["min"]:
        return False
    if "min_exclusive" in band and value <= band["min_exclusive"]:
        return False
    if "max" in band and value > band["max"]:
        return False
    return not ("max_exclusive" in band and value >= band["max_exclusive"])


def _score_range(field: str, spec: dict[str, Any], value: float):
    if not math.isfinite(value):
        return None, UnscorableIssue(
            field=field,
            reason="not_a_finite_number",
            detail=f"{value!r} is not a finite number",
        )
    if spec.get("integer_only") and not float(value).is_integer():
        return None, UnscorableIssue(
            field=field,
            reason="not_a_whole_number",
            detail=f"{value} is between chart bands; the chart lists whole numbers only",
        )
    matches = [band for band in spec["bands"] if _in_band(value, band)]
    if len(matches) != 1:
        return None, UnscorableIssue(
            field=field,
            reason="no_matching_band",
            detail=f"{value} matched {len(matches)} chart bands",
        )
    band = matches[0]
    return ParameterScore(
        field=field, value=value, score=band["score"], rule_id=band["rule_id"]
    ), None


def _score_category(field: str, spec: dict[str, Any], value: Any):
    wanted = value.strip().lower() if isinstance(value, str) else value
    for entry in spec["values"]:
        if entry["value"] == wanted and type(entry["value"]) is type(wanted):
            return (
                ParameterScore(
                    field=field,
                    value=wanted,
                    score=entry["score"],
                    rule_id=entry["rule_id"],
                ),
                None,
            )
    return None, UnscorableIssue(
        field=field,
        reason="unrecognised_value",
        detail=f"{value!r} is not a value listed on the chart",
    )


def score_tews(
    observations: PatientObservations, protocol: dict[str, Any] | None = None
) -> TEWSResult:
    protocol = protocol if protocol is not None else load_protocol()

    scores: list[ParameterScore] = []
    missing: list[str] = []
    issues: list[UnscorableIssue] = []

    for spec in protocol["parameters"].values():
        field = spec["contract_field"]
        value = getattr(observations, field)

        if value is None:
            missing.append(field)
            continue

        if spec["type"] == "range":
            scored, issue = _score_range(field, spec, value)
        else:
            scored, issue = _score_category(field, spec, value)

        if scored is not None:
            scores.append(scored)
        if issue is not None:
            issues.append(issue)

    base = {
        "protocol_id": protocol["protocol_id"],
        "protocol_version": protocol["protocol_version"],
        "parameter_scores": scores,
        "missing": missing,
        "unscorable": issues,
    }

    if missing or issues:
        return TEWSResult(status="abstained", **base)

    total = sum(item.score for item in scores)
    band = next(b for b in protocol["bands"] if _in_band(total, b))
    return TEWSResult(
        status="scored",
        total=total,
        priority=band["priority"],
        band_rule_id=band["rule_id"],
        **base,
    )
