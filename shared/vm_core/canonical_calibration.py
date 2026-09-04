from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from .canonical_outcomes import canonical_inference_outcomes
from .intelligence_audit import AuditQuery, query_intelligence_events
from .paths import project_root


_INFERENCE_TYPE = "intelligence.inference.relationship_reengagement_opportunity"
_MIN_KNOWN_OUTCOMES = 8


@dataclass(frozen=True, slots=True)
class CanonicalCalibration:
    status: str
    outcome_events: int
    known_binary_outcomes: int
    positive_outcomes: int
    negative_outcomes: int
    positive_rate: float | None
    average_predicted_confidence: float | None
    calibration_gap: float | None
    brier_score: float | None
    automatic_rule_change: bool = False
    automatic_execution: bool = False


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _inference_index(root: Path) -> dict[int, dict[str, Any]]:
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_INFERENCE_TYPE,
            source="vm_core",
            subject_type="chat",
            limit=5000,
        ),
        root=root,
    )
    return {int(row.get("id") or 0): row for row in rows if int(row.get("id") or 0) > 0}


def canonical_calibration_report(*, root: Path | None = None) -> CanonicalCalibration:
    """Evaluate canonical inference confidence against verified binary outcomes.

    The report is descriptive only. It never changes source trust, scoring rules,
    thresholds, recommendation state or execution authority.
    """
    root = root or project_root()
    outcomes = canonical_inference_outcomes(root=root, limit=5000)
    inferences = _inference_index(root)

    pairs: list[tuple[float, int]] = []
    positives = 0
    negatives = 0
    for outcome in outcomes:
        attributes = _payload(outcome).get("attributes")
        if not isinstance(attributes, dict):
            continue
        outcome_type = str(attributes.get("outcome_type") or "").upper()
        if outcome_type not in {"POSITIVE", "NEGATIVE"}:
            continue
        try:
            inference_event_id = int(attributes.get("inference_event_id") or 0)
        except (TypeError, ValueError):
            continue
        inference = inferences.get(inference_event_id)
        if inference is None:
            continue
        try:
            predicted = float(_payload(inference).get("confidence"))
        except (TypeError, ValueError):
            continue
        predicted = max(0.0, min(1.0, predicted))
        actual = 1 if outcome_type == "POSITIVE" else 0
        pairs.append((predicted, actual))
        positives += actual
        negatives += 1 - actual

    known = len(pairs)
    if known:
        positive_rate = positives / known
        avg_confidence = sum(predicted for predicted, _actual in pairs) / known
        gap = avg_confidence - positive_rate
        brier = sum((predicted - actual) ** 2 for predicted, actual in pairs) / known
    else:
        positive_rate = None
        avg_confidence = None
        gap = None
        brier = None

    status = "INSUFFICIENT_DATA"
    if known >= _MIN_KNOWN_OUTCOMES:
        if brier is not None and brier <= 0.15 and (gap is None or abs(gap) <= 0.10):
            status = "WELL_CALIBRATED"
        elif brier is not None and brier <= 0.25 and (gap is None or abs(gap) <= 0.20):
            status = "ACCEPTABLE"
        else:
            status = "REVIEW_REQUIRED"

    return CanonicalCalibration(
        status=status,
        outcome_events=len(outcomes),
        known_binary_outcomes=known,
        positive_outcomes=positives,
        negative_outcomes=negatives,
        positive_rate=round(positive_rate, 4) if positive_rate is not None else None,
        average_predicted_confidence=round(avg_confidence, 4) if avg_confidence is not None else None,
        calibration_gap=round(gap, 4) if gap is not None else None,
        brier_score=round(brier, 4) if brier is not None else None,
    )


def canonical_calibration_summary(*, root: Path | None = None) -> dict[str, Any]:
    result = asdict(canonical_calibration_report(root=root))
    result["minimum_known_outcomes"] = _MIN_KNOWN_OUTCOMES
    return result
