from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _parse_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evidence_quality(evidence: dict[str, Any] | None) -> float:
    """Return structural evidence quality independent of recommendation confidence."""
    data = dict(evidence or {})
    if not data:
        return 0.0
    signals = 0.0
    possible = 0.0
    for key, weight in (
        ("source", 0.20),
        ("event_id", 0.15),
        ("correlation_id", 0.15),
        ("observed_at_utc", 0.15),
        ("subject_id", 0.10),
        ("supporting_signals", 0.25),
    ):
        possible += weight
        value = data.get(key)
        if isinstance(value, (list, tuple, set)):
            present = len(value) > 0
        else:
            present = value not in (None, "", False)
        if present:
            signals += weight
    return round(_clamp01(signals / possible if possible else 0.0), 3)


def freshness_score(evidence: dict[str, Any] | None, *, now: datetime | None = None) -> float:
    """Score evidence recency without changing or deleting stale evidence."""
    observed = _parse_utc(dict(evidence or {}).get("observed_at_utc"))
    if observed is None:
        return 0.0
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_hours = max(0.0, (current - observed).total_seconds() / 3600.0)
    if age_hours <= 24:
        score = 1.0
    elif age_hours <= 24 * 7:
        score = 0.85
    elif age_hours <= 24 * 30:
        score = 0.65
    elif age_hours <= 24 * 90:
        score = 0.45
    else:
        score = 0.25
    return round(score, 3)


def source_reliability_score(evidence: dict[str, Any] | None) -> float:
    """Use explicit source reliability when supplied; otherwise remain neutral/conservative."""
    data = dict(evidence or {})
    explicit = data.get("source_reliability")
    if explicit is not None:
        try:
            return round(_clamp01(float(explicit)), 3)
        except (TypeError, ValueError):
            return 0.0
    return 0.5 if data.get("source") else 0.0


def calibrated_confidence(
    recommendation_confidence: float,
    *,
    verification_confidence: float | None = None,
    evidence: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Combine independent trust signals conservatively without granting authority.

    Missing verification never inherits recommendation confidence. This prevents a
    recommendation from validating itself merely because its own confidence is high.
    """
    rec = _clamp01(recommendation_confidence)
    quality = evidence_quality(evidence)
    freshness = freshness_score(evidence, now=now)
    reliability = source_reliability_score(evidence)
    verification_available = verification_confidence is not None
    verify = _clamp01(verification_confidence) if verification_available else 0.0

    if verification_available:
        supporting = (0.50 * verify) + (0.25 * quality) + (0.15 * freshness) + (0.10 * reliability)
    else:
        # No independent verification: cap trust using evidence alone and apply a
        # conservative penalty rather than silently copying recommendation confidence.
        supporting = 0.55 * ((0.50 * quality) + (0.30 * freshness) + (0.20 * reliability))
    combined = min(rec, supporting)
    return {
        "recommendation_confidence": round(rec, 3),
        "verification_confidence": round(verify, 3) if verification_available else None,
        "verification_available": verification_available,
        "evidence_quality": round(quality, 3),
        "freshness_score": round(freshness, 3),
        "source_reliability": round(reliability, 3),
        "calibrated_confidence": round(_clamp01(combined), 3),
    }


def recommendation_confidence_view(row: dict[str, Any]) -> dict[str, Any]:
    evidence_raw = row.get("evidence_json")
    if isinstance(evidence_raw, str):
        try:
            parsed = json.loads(evidence_raw or "{}")
            evidence = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            evidence = {}
    else:
        evidence = dict(evidence_raw or {})
    verification = evidence.get("verification_confidence")
    try:
        verification_value = float(verification) if verification is not None else None
    except (TypeError, ValueError):
        verification_value = None
    metrics = calibrated_confidence(
        float(row.get("confidence") or 0),
        verification_confidence=verification_value,
        evidence=evidence,
    )
    return {
        "recommendation_key": row.get("recommendation_key"),
        "rule_id": row.get("rule_id"),
        **metrics,
        "automatic_execution": False,
    }
