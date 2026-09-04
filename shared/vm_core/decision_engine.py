from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .confidence import recommendation_confidence_view
from .db import PlatformDB
from .paths import project_root
from .prediction_intelligence import prediction_summary
from .rule_health import rule_health
from .rule_registry import effective_score_delta


def _clamp100(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _evidence(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("evidence_json")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return dict(raw or {})


def _component(evidence: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return _clamp100(float(evidence.get(key, default)))
    except (TypeError, ValueError):
        return _clamp100(default)


def _component_available(evidence: dict[str, Any], key: str) -> bool:
    if key not in evidence or evidence.get(key) is None:
        return False
    try:
        float(evidence[key])
        return True
    except (TypeError, ValueError):
        return False


def _duplicate_signature(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(item.get("recommendation_type") or ""),
        str(item.get("subject_type") or ""),
        str(item.get("subject_id") or ""),
        str(item.get("action") or "").strip().lower(),
    )


def ranked_decisions(root: Path | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    """Rank proposed legacy recommendations without accepting or executing any action."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    health = {(r["rule_id"], r["source_rule_version"]): r for r in rule_health(root)}
    rows = db.recommendations(limit=max(1, int(limit)) * 4, status="PROPOSED")
    decisions: list[dict[str, Any]] = []

    for row in rows:
        evidence = _evidence(row)
        confidence = recommendation_confidence_view(row)
        governed_delta = effective_score_delta(
            str(row.get("rule_id") or ""),
            int(row.get("rule_version") or 1),
            str(row.get("subject_id") or ""),
            root,
        )
        priority = _clamp100(float(row.get("priority") or 0) + governed_delta)
        risk_assessed = _component_available(evidence, "risk_score")
        risk = _component(evidence, "risk_score", 50)
        urgency = _component(evidence, "urgency_score", priority)
        opportunity = _component(evidence, "opportunity_score", priority)
        estimated_value = _component(evidence, "estimated_value_score", opportunity)
        effort = _component(evidence, "effort_score", 50)
        calibrated = float(confidence["calibrated_confidence"])
        health_row = health.get((str(row.get("rule_id") or ""), int(row.get("rule_version") or 1)))
        health_penalty = 20.0 if health_row and health_row.get("status") == "DEGRADED" else 0.0

        score = (
            0.30 * priority
            + 0.20 * urgency
            + 0.20 * opportunity
            + 0.15 * estimated_value
            + 0.15 * (calibrated * 100.0)
            - 0.20 * risk
            - 0.10 * effort
            - health_penalty
        )
        decision_score = round(_clamp100(score), 2)
        decisions.append({
            "recommendation_key": row["recommendation_key"],
            "recommendation_type": row["recommendation_type"],
            "subject_type": row.get("subject_type"),
            "subject_id": row.get("subject_id"),
            "rule_id": row["rule_id"],
            "rule_version": int(row["rule_version"]),
            "decision_score": decision_score,
            "base_priority": round(float(row.get("priority") or 0), 2),
            "governed_score_delta": round(governed_delta, 2),
            "risk_score": risk,
            "risk_assessed": risk_assessed,
            "urgency_score": urgency,
            "opportunity_score": opportunity,
            "estimated_value_score": estimated_value,
            "effort_score": effort,
            "confidence": confidence,
            "rule_health": health_row["status"] if health_row else "UNMONITORED",
            "action": row["action"],
            "rationale": row["rationale"],
            "status": row["status"],
            "automatic_acceptance": False,
            "automatic_execution": False,
        })

    decisions.sort(
        key=lambda item: (
            -item["decision_score"],
            -item["confidence"]["calibrated_confidence"],
            item["recommendation_key"],
        )
    )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in decisions:
        signature = _duplicate_signature(item)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(item)
    return deduped[: max(1, int(limit))]


def _canonical_disposition(prediction: dict[str, Any]) -> str:
    probability = float(prediction.get("probability") or 0.0)
    lower = float(prediction.get("lower_bound") or 0.0)
    if bool(prediction.get("risk_review_required")):
        return "RISK_REVIEW_FIRST"
    if probability >= 0.70 and lower >= 0.50:
        return "PRIORITISE_OPERATOR_REVIEW"
    if probability >= 0.55:
        return "REVIEW_WHEN_AVAILABLE"
    return "DEFER_LOW_EXPECTED_VALUE"


def canonical_decisions(
    root: Path | None = None,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Rank canonical operator-review choices from Predictions without taking action.

    This is the shared Brain Decision Engine surface. It consumes the existing
    prediction/risk/opportunity chain and produces an operator-review disposition,
    not an executable instruction. No recommendation is created or accepted here.
    """
    root = root or project_root()
    try:
        requested = max(1, min(500, int(limit)))
    except (TypeError, ValueError):
        requested = 50
    predictions = prediction_summary(root=root, limit=requested)
    rows: list[dict[str, Any]] = []
    for prediction in predictions.get("predictions", []):
        subject = str(prediction.get("canonical_subject_id") or "").strip()
        if not subject:
            continue
        try:
            probability = max(0.0, min(1.0, float(prediction.get("probability") or 0.0)))
            lower = max(0.0, min(1.0, float(prediction.get("lower_bound") or 0.0)))
            confidence = max(0.0, min(1.0, float(prediction.get("source_confidence") or 0.0)))
            risk = max(0.0, min(100.0, float(prediction.get("risk_score") or 0.0)))
        except (TypeError, ValueError):
            continue
        raw_score = probability * 60.0 + lower * 20.0 + confidence * 20.0 - risk * 0.25
        score = round(_clamp100(raw_score), 2)
        disposition = _canonical_disposition(prediction)
        reasons = [
            f"forecast_probability={probability:.4f}",
            f"forecast_lower_bound={lower:.4f}",
            f"source_confidence={confidence:.4f}",
            f"risk_score={risk:.2f}",
        ]
        if prediction.get("empirical_base_rate_used"):
            reasons.append("verified_outcome_base_rate_used")
        if prediction.get("risk_review_required"):
            reasons.append("risk_review_required")
        rows.append({
            "canonical_subject_id": subject,
            "decision_type": "operator_review_priority",
            "disposition": disposition,
            "decision_score": score,
            "forecast_probability": probability,
            "forecast_lower_bound": lower,
            "forecast_upper_bound": prediction.get("upper_bound"),
            "prediction_method": prediction.get("method"),
            "source_opportunity_type": prediction.get("source_opportunity_type"),
            "source_opportunity_score": prediction.get("source_opportunity_score"),
            "risk_adjusted_score": prediction.get("risk_adjusted_score"),
            "risk_score": risk,
            "risk_level": prediction.get("risk_level"),
            "source_confidence": confidence,
            "reasons": reasons,
            "requires_human_review": True,
            "decision_is_advisory": True,
            "recommendation_created": False,
            "automatic_conflict_resolution": False,
            "automatic_acceptance": False,
            "automatic_execution": False,
            "automatic_threshold_change": False,
            "automatic_rule_change": False,
            "external_action_authority": False,
        })

    rows.sort(
        key=lambda item: (
            item["disposition"] == "RISK_REVIEW_FIRST",
            -float(item["decision_score"]),
            -float(item["forecast_probability"]),
            str(item["canonical_subject_id"]),
        )
    )
    return rows[:requested]


def decision_summary(root: Path | None = None, *, limit: int = 20) -> dict[str, Any]:
    rows = ranked_decisions(root, limit=limit)
    subjects: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        subject_key = (str(row.get("subject_type") or ""), str(row.get("subject_id") or ""))
        subjects.setdefault(subject_key, []).append(row)

    conflicts: list[dict[str, Any]] = []
    for (subject_type, subject_id), items in subjects.items():
        recommendation_types = sorted({str(item["recommendation_type"]) for item in items})
        actions = sorted({str(item["action"]) for item in items})
        if len(recommendation_types) > 1 or len(actions) > 1:
            conflicts.append({
                "subject_type": subject_type,
                "subject_id": subject_id,
                "recommendation_keys": [item["recommendation_key"] for item in items],
                "recommendation_types": recommendation_types,
                "requires_human_resolution": True,
                "automatic_resolution": False,
            })

    canonical_rows = canonical_decisions(root, limit=limit)
    disposition_counts: dict[str, int] = {}
    for row in canonical_rows:
        disposition = str(row["disposition"])
        disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1

    return {
        "decision_count": len(rows),
        "top_decisions": rows,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "duplicate_suppression": True,
        "unknown_risk_default": 50,
        "canonical_decision_count": len(canonical_rows),
        "canonical_top_decisions": canonical_rows,
        "canonical_disposition_counts": dict(sorted(disposition_counts.items())),
        "canonical_decisions_read_only": True,
        "automatic_conflict_resolution": False,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "automatic_threshold_change": False,
        "automatic_rule_change": False,
        "external_action_authority": False,
    }
