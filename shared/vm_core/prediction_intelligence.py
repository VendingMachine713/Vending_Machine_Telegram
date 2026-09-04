from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical_review_calibration import canonical_review_calibration_summary
from .paths import project_root
from .risk_fusion import risk_adjusted_canonical_opportunities

_MIN_EMPIRICAL_OUTCOMES = 8
_FORECAST_HORIZON_HOURS = 48


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _safe_limit(value: Any, *, default: int = 50) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(500, parsed))


def _prediction_probability(
    *,
    risk_adjusted_score: float,
    confidence: float,
    empirical_positive_rate: float | None,
    empirical_ready: bool,
) -> tuple[float, str]:
    heuristic = _clamp01(risk_adjusted_score / 100.0)
    confidence = _clamp01(confidence)
    confidence_adjusted = 0.5 + (heuristic - 0.5) * (0.55 + 0.45 * confidence)
    if empirical_ready and empirical_positive_rate is not None:
        probability = confidence_adjusted * 0.70 + _clamp01(empirical_positive_rate) * 0.30
        return _clamp01(probability), "HEURISTIC_PLUS_VERIFIED_OUTCOME_BASE_RATE"
    return _clamp01(confidence_adjusted), "HEURISTIC_BASELINE"


def prediction_summary(
    *,
    root: Path | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Forecast near-term positive review value without taking or recommending action."""
    root = root or project_root()
    calibration = canonical_review_calibration_summary(root=root)
    try:
        known = max(0, int(calibration.get("known_binary_outcomes") or 0))
    except (TypeError, ValueError):
        known = 0
    positive_rate_raw = calibration.get("positive_rate")
    try:
        positive_rate = float(positive_rate_raw) if positive_rate_raw is not None else None
    except (TypeError, ValueError):
        positive_rate = None
    empirical_ready = known >= _MIN_EMPIRICAL_OUTCOMES and positive_rate is not None

    opportunities = risk_adjusted_canonical_opportunities(root=root, limit=_safe_limit(limit))
    predictions: list[dict[str, Any]] = []
    for row in opportunities:
        subject = str(row.get("canonical_subject_id") or "").strip()
        if not subject:
            continue
        try:
            adjusted = max(0.0, min(100.0, float(row.get("risk_adjusted_score") or 0.0)))
            confidence = _clamp01(float(row.get("confidence") or 0.0))
        except (TypeError, ValueError):
            continue
        probability, method = _prediction_probability(
            risk_adjusted_score=adjusted,
            confidence=confidence,
            empirical_positive_rate=positive_rate,
            empirical_ready=empirical_ready,
        )
        uncertainty = 0.08 + (1.0 - confidence) * 0.22
        lower = _clamp01(probability - uncertainty)
        upper = _clamp01(probability + uncertainty)
        predictions.append(
            {
                "canonical_subject_id": subject,
                "prediction_type": "positive_operator_review_value",
                "forecast_horizon_hours": _FORECAST_HORIZON_HOURS,
                "probability": round(probability, 4),
                "lower_bound": round(lower, 4),
                "upper_bound": round(upper, 4),
                "method": method,
                "source_opportunity_type": row.get("opportunity_type"),
                "source_opportunity_score": row.get("opportunity_score"),
                "risk_adjusted_score": adjusted,
                "risk_score": row.get("risk_score"),
                "risk_level": row.get("risk_level"),
                "source_confidence": confidence,
                "risk_review_required": bool(row.get("risk_review_required")),
                "candidate_visible": True,
                "calibration_status": calibration.get("status"),
                "verified_outcome_count": known,
                "empirical_base_rate_used": empirical_ready,
                "trained_model": False,
                "prediction_is_advisory": True,
                "recommendation_created": False,
                "automatic_acceptance": False,
                "automatic_execution": False,
                "automatic_threshold_change": False,
                "automatic_rule_change": False,
                "external_action_authority": False,
            }
        )

    predictions.sort(
        key=lambda item: (
            -float(item["probability"]),
            -float(item["source_confidence"]),
            str(item["canonical_subject_id"]),
        )
    )
    return {
        "status": "OK" if predictions else "NO_EVIDENCE",
        "prediction_count": len(predictions),
        "predictions": predictions,
        "forecast_horizon_hours": _FORECAST_HORIZON_HOURS,
        "calibration_status": calibration.get("status"),
        "verified_outcome_count": known,
        "minimum_empirical_outcomes": _MIN_EMPIRICAL_OUTCOMES,
        "empirical_base_rate_used": empirical_ready,
        "read_only": True,
        "trained_model": False,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "automatic_threshold_change": False,
        "automatic_rule_change": False,
        "external_action_authority": False,
    }
