from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3
from typing import Any

from .db import PlatformDB
from .paths import project_root


_RECOMMENDATION_TYPE = "canonical_relationship_reengagement_review"
_MIN_KNOWN_OUTCOMES = 8


@dataclass(frozen=True, slots=True)
class CanonicalReviewCalibration:
    status: str
    outcome_events: int
    known_binary_outcomes: int
    positive_outcomes: int
    negative_outcomes: int
    neutral_outcomes: int
    unknown_outcomes: int
    positive_rate: float | None
    average_recommendation_confidence: float | None
    calibration_gap: float | None
    brier_score: float | None
    average_realized_value_score: float | None
    automatic_threshold_change: bool = False
    automatic_rule_change: bool = False
    automatic_execution: bool = False


def _readonly_rows(root: Path) -> list[dict[str, Any]]:
    """Read canonical review outcomes without creating or migrating platform state."""
    path = PlatformDB(root=root).path
    if not path.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        tables = {
            str(row[0])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('intelligence_recommendations','intelligence_outcomes')"
            ).fetchall()
        }
        if tables != {"intelligence_recommendations", "intelligence_outcomes"}:
            return []
        rows = con.execute(
            """
            SELECT
                o.outcome_type,
                o.value_score,
                o.confidence AS outcome_confidence,
                r.confidence AS recommendation_confidence,
                r.recommendation_type,
                r.recommendation_key,
                r.id AS recommendation_id
            FROM intelligence_outcomes o
            JOIN intelligence_recommendations r ON r.id=o.recommendation_id
            WHERE r.recommendation_type=?
            ORDER BY o.id ASC
            """,
            (_RECOMMENDATION_TYPE,),
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def canonical_review_calibration_report(
    *, root: Path | None = None
) -> CanonicalReviewCalibration:
    """Evaluate canonical review recommendation confidence against verified outcomes.

    Predicted probability comes from the original recommendation confidence, not the
    operator's confidence in the later outcome observation. The result is descriptive
    only and never changes thresholds, rules, trust values or execution authority.
    """
    root = root or project_root()
    rows = _readonly_rows(root)

    pairs: list[tuple[float, int]] = []
    values: list[float] = []
    positives = 0
    negatives = 0
    neutrals = 0
    unknowns = 0

    for row in rows:
        outcome_type = str(row.get("outcome_type") or "UNKNOWN").upper()
        try:
            values.append(float(row.get("value_score") or 0.0))
        except (TypeError, ValueError):
            pass
        if outcome_type == "NEUTRAL":
            neutrals += 1
            continue
        if outcome_type == "UNKNOWN":
            unknowns += 1
            continue
        if outcome_type not in {"POSITIVE", "NEGATIVE"}:
            unknowns += 1
            continue
        try:
            predicted = float(row.get("recommendation_confidence"))
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

    avg_value = sum(values) / len(values) if values else None
    status = "INSUFFICIENT_DATA"
    if known >= _MIN_KNOWN_OUTCOMES:
        if brier is not None and brier <= 0.15 and (gap is None or abs(gap) <= 0.10):
            status = "WELL_CALIBRATED"
        elif brier is not None and brier <= 0.25 and (gap is None or abs(gap) <= 0.20):
            status = "ACCEPTABLE"
        else:
            status = "REVIEW_REQUIRED"

    return CanonicalReviewCalibration(
        status=status,
        outcome_events=len(rows),
        known_binary_outcomes=known,
        positive_outcomes=positives,
        negative_outcomes=negatives,
        neutral_outcomes=neutrals,
        unknown_outcomes=unknowns,
        positive_rate=round(positive_rate, 4) if positive_rate is not None else None,
        average_recommendation_confidence=(
            round(avg_confidence, 4) if avg_confidence is not None else None
        ),
        calibration_gap=round(gap, 4) if gap is not None else None,
        brier_score=round(brier, 4) if brier is not None else None,
        average_realized_value_score=round(avg_value, 2) if avg_value is not None else None,
    )


def canonical_review_calibration_summary(*, root: Path | None = None) -> dict[str, Any]:
    result = asdict(canonical_review_calibration_report(root=root))
    result["minimum_known_outcomes"] = _MIN_KNOWN_OUTCOMES
    result["recommendation_type"] = _RECOMMENDATION_TYPE
    return result
