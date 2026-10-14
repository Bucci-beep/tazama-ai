"""Combine nurse-identified signs with the TEWS band into a SATS priority.

Rule from the chart: the final priority is the highest of the sign level and the TEWS band.
The order of levels is read from the protocol data files; no clinical value lives here.

Signs are identified by the nurse. Tazama never detects them.
  signs is None -> the nurse has not assessed signs yet
  signs == []   -> the nurse assessed and found none
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tazama.clinical.tews import TEWSResult, load_protocol, score_tews
from tazama.mcp.contracts import PatientObservations

DEFAULT_DISCRIMINATORS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "protocol" / "discriminators_adult.json"
)


class PriorityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "minimum_only", "abstained"]
    priority: str | None = None
    priority_at_least: str | None = None
    matched_sign_ids: list[str] = Field(default_factory=list)
    unknown_sign_ids: list[str] = Field(default_factory=list)
    tews: TEWSResult
    reasons: list[str] = Field(default_factory=list)
    protocol_version: str


def load_discriminators(path: Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else DEFAULT_DISCRIMINATORS_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def _tews_reason(tews: TEWSResult) -> str:
    parts: list[str] = []
    if tews.missing:
        parts.append("missing " + ", ".join(tews.missing))
    if tews.unscorable:
        parts.append("off-chart " + ", ".join(issue.field for issue in tews.unscorable))
    return "TEWS not calculated: " + "; ".join(parts)


def determine_priority(
    observations: PatientObservations,
    signs: list[str] | None,
    tews_protocol: dict[str, Any] | None = None,
    discriminators: dict[str, Any] | None = None,
) -> PriorityResult:
    tews_protocol = tews_protocol if tews_protocol is not None else load_protocol()
    discriminators = discriminators if discriminators is not None else load_discriminators()

    order = [band["priority"] for band in tews_protocol["bands"]]
    top = len(order) - 1
    level_of = {
        sign["sign_id"]: level["priority"]
        for level in discriminators["levels"]
        for sign in level["signs"]
    }

    tews = score_tews(observations, tews_protocol)
    version = tews_protocol["protocol_version"]

    def build(
        status: Literal["complete", "minimum_only", "abstained"],
        *,
        priority: str | None = None,
        at_least: str | None = None,
        matched: list[str] | None = None,
        unknown: list[str] | None = None,
        reasons: list[str] | None = None,
    ) -> PriorityResult:
        return PriorityResult(
            status=status,
            priority=priority,
            priority_at_least=at_least,
            matched_sign_ids=matched or [],
            unknown_sign_ids=unknown or [],
            tews=tews,
            reasons=reasons or [],
            protocol_version=version,
        )

    requested = list(dict.fromkeys(signs)) if signs is not None else None
    unknown = [s for s in (requested or []) if s not in level_of]
    if unknown:
        return build(
            "abstained",
            unknown=unknown,
            reasons=["Unknown sign ids; nothing was guessed"],
        )

    matched = requested or []
    sign_rank = max((order.index(level_of[s]) for s in matched), default=None)
    tews_rank = (
        order.index(tews.priority)
        if tews.status == "scored" and tews.priority is not None
        else None
    )

    # The highest level cannot be exceeded, so no vital signs are needed.
    if sign_rank == top:
        return build("complete", priority=order[top], matched=matched)

    if requested is None:
        reasons = ["Signs have not been assessed by the nurse"]
        if tews_rank is None:
            return build("abstained", reasons=[*reasons, _tews_reason(tews)])
        return build("minimum_only", at_least=order[tews_rank], reasons=reasons)

    if tews_rank is not None:
        highest = max(rank for rank in (sign_rank, tews_rank) if rank is not None)
        return build("complete", priority=order[highest], matched=matched)

    reasons = [_tews_reason(tews)]
    if sign_rank is not None:
        return build("minimum_only", at_least=order[sign_rank], matched=matched, reasons=reasons)
    return build("abstained", reasons=reasons)
