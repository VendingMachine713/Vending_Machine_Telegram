from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

from .learning import outcomes, rule_performance
from .paths import project_root


MIN_KNOWN_OUTCOMES = 8
MAX_PROPOSED_SCORE_DELTA = 10.0


@dataclass(frozen=True)
class CalibrationProposal:
    rule_id: str
    rule_version: int
    status: str
    sample_size: int
    known_outcomes: int
    positive_rate: float | None
    weighted_value: float
    calibration_gap: float | None
    proposed_score_delta: float
    rationale: str
    automatic_application: bool = False


def _wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float | None:
    if total <= 0:
        return None
    phat = successes / total
    denom = 1 + (z * z / total)
    centre = phat + (z * z / (2 * total))
    spread = z * sqrt((phat * (1 - phat) / total) + (z * z / (4 * total * total)))
    return max(0.0, min(1.0, (centre - spread) / denom))


def _rule_rows(root: Path) -> dict[tuple[str, int], list[dict[str, Any]]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in outcomes(root, limit=10000):
        key = (str(row["rule_id"]), int(row["rule_version"]))
        grouped.setdefault(key, []).append(row)
    return grouped


def calibration_report(root: Path | None = None) -> list[dict[str, Any]]:
    """Return advisory calibration proposals derived from verified outcomes.

    No rule, threshold, score or bot configuration is modified by this function.
    """
    root = root or project_root()
    performance = {
        (str(item["rule_id"]), int(item["rule_version"])): item
        for item in rule_performance(root)
    }
    grouped = _rule_rows(root)
    report: list[dict[str, Any]] = []

    for key, items in grouped.items():
        rule_id, rule_version = key
        perf = performance.get(key, {})
        known = [r for r in items if str(r["outcome_type"]) != "UNKNOWN"]
        positives = sum(1 for r in known if str(r["outcome_type"]) == "POSITIVE")
        known_count = len(known)
        positive_rate = positives / known_count if known_count else None
        weighted_value = float(perf.get("confidence_weighted_value") or 0.0)

        recommendation_confidences: list[float] = []
        for row in known:
            try:
                recommendation_confidences.append(float(row.get("confidence") or 0.0))
            except (TypeError, ValueError):
                pass
        avg_outcome_confidence = (
            sum(recommendation_confidences) / len(recommendation_confidences)
            if recommendation_confidences else None
        )
        calibration_gap = (
            avg_outcome_confidence - positive_rate
            if avg_outcome_confidence is not None and positive_rate is not None
            else None
        )

        lower_bound = _wilson_lower_bound(positives, known_count)
        status = "INSUFFICIENT_DATA"
        proposed_delta = 0.0
        rationale = f"Need at least {MIN_KNOWN_OUTCOMES} known outcomes before calibration proposals are actionable."

        if known_count >= MIN_KNOWN_OUTCOMES:
            if lower_bound is not None and lower_bound >= 0.65 and weighted_value >= 20:
                status = "STRONG"
                proposed_delta = min(MAX_PROPOSED_SCORE_DELTA, 5.0)
                rationale = "Rule has sustained positive verified outcomes with a conservative lower-bound success rate."
            elif positive_rate is not None and positive_rate <= 0.35 and weighted_value <= -15:
                status = "WEAK"
                proposed_delta = max(-MAX_PROPOSED_SCORE_DELTA, -7.5)
                rationale = "Rule shows persistently weak verified outcomes and negative confidence-weighted value."
            elif calibration_gap is not None and calibration_gap >= 0.20:
                status = "OVERCONFIDENT"
                proposed_delta = -5.0
                rationale = "Verified outcomes materially underperform the observed confidence level."
            else:
                status = "STABLE"
                rationale = "Outcome evidence does not justify a bounded scoring adjustment."

        proposal = CalibrationProposal(
            rule_id=rule_id,
            rule_version=rule_version,
            status=status,
            sample_size=len(items),
            known_outcomes=known_count,
            positive_rate=positive_rate,
            weighted_value=round(weighted_value, 2),
            calibration_gap=round(calibration_gap, 4) if calibration_gap is not None else None,
            proposed_score_delta=proposed_delta,
            rationale=rationale,
        )
        report.append(proposal.__dict__)

    report.sort(key=lambda item: (item["status"] == "INSUFFICIENT_DATA", item["rule_id"], item["rule_version"]))
    return report


def calibration_summary(root: Path | None = None) -> dict[str, Any]:
    rows = calibration_report(root)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "rules": len(rows),
        "counts": counts,
        "proposals": rows,
        "minimum_known_outcomes": MIN_KNOWN_OUTCOMES,
        "max_proposed_score_delta": MAX_PROPOSED_SCORE_DELTA,
        "automatic_application": False,
        "automatic_execution": False,
    }
