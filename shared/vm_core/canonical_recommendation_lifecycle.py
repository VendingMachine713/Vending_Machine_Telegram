from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .governance import RecommendationGovernanceError, transition_recommendation
from .intelligence_audit import AuditQuery, query_intelligence_events
from .paths import project_root


_RECOMMENDATION_TYPE = "canonical_relationship_reengagement_review"
_INFERENCE_TYPE = "intelligence.inference.relationship_reengagement_opportunity"


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_inference(root: Path, subject_id: str) -> dict[str, Any] | None:
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_INFERENCE_TYPE,
            source="vm_core",
            subject_type="chat",
            subject_id=subject_id,
            limit=20,
        ),
        root=root,
    )
    return max(rows, key=lambda row: int(row.get("id") or 0), default=None)


def expire_canonical_review_proposals(
    *,
    root: Path | None = None,
    stale_after_hours: float = 72.0,
    minimum_opportunity_score: float = 60.0,
    now: datetime | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Expire obsolete PROPOSED canonical review metadata.

    Accepted recommendations are intentionally out of scope. This lifecycle function
    only closes stale or superseded proposals and records governed EXPIRED events. It
    never accepts, executes, schedules, or sends anything.
    """
    root = root or project_root()
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stale_hours = max(1.0, float(stale_after_hours))
    minimum_score = max(0.0, min(100.0, float(minimum_opportunity_score)))
    db = PlatformDB(root=root)
    db.init()
    rows = [
        row
        for row in db.recommendations(limit=max(1, int(limit)), status="PROPOSED")
        if str(row.get("recommendation_type") or "") == _RECOMMENDATION_TYPE
    ]
    result: dict[str, Any] = {
        "considered": len(rows),
        "expired": 0,
        "kept": 0,
        "invalid": 0,
        "reasons": {},
        "accepted_touched": 0,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }

    for recommendation in rows:
        subject_id = str(recommendation.get("subject_id") or "").strip()
        recommendation_key = str(recommendation.get("recommendation_key") or "").strip()
        evidence = _json_dict(recommendation.get("evidence_json"))
        expected_event_id = int(evidence.get("canonical_inference_event_id") or 0)
        expected_signature = str(evidence.get("support_signature") or "").strip()
        if not subject_id or not recommendation_key or expected_event_id <= 0 or not expected_signature:
            reason = "invalid_provenance"
        else:
            latest = _latest_inference(root, subject_id)
            if latest is None:
                reason = "missing_canonical_inference"
            else:
                latest_payload = _json_dict(latest.get("payload_json"))
                latest_attributes = latest_payload.get("attributes")
                latest_attributes = latest_attributes if isinstance(latest_attributes, dict) else {}
                latest_signature = str(latest_attributes.get("support_signature") or "").strip()
                created = _parse_utc(latest.get("created_at_utc"))
                if created is None:
                    reason = "invalid_inference_timestamp"
                elif max(0.0, (now - created).total_seconds() / 3600.0) > stale_hours:
                    reason = "stale_canonical_inference"
                elif int(latest.get("id") or 0) != expected_event_id and latest_signature != expected_signature:
                    reason = "superseded_canonical_inference"
                elif bool(latest_attributes.get("suppressed")):
                    reason = "latest_inference_suppressed"
                else:
                    try:
                        latest_score = float(latest_attributes.get("opportunity_score"))
                    except (TypeError, ValueError):
                        latest_score = -1.0
                    if latest_score < minimum_score:
                        reason = "latest_inference_below_threshold"
                    else:
                        reason = "keep"

        if reason == "keep":
            result["kept"] += 1
            continue

        try:
            transition_recommendation(
                recommendation_key,
                "EXPIRED",
                actor="vm_core.canonical_lifecycle",
                note=reason,
                root=root,
            )
        except RecommendationGovernanceError:
            result["invalid"] += 1
            continue
        result["expired"] += 1
        reasons = result["reasons"]
        reasons[reason] = int(reasons.get(reason, 0)) + 1

    return result


def canonical_review_lifecycle_summary(*, root: Path | None = None, limit: int = 500) -> dict[str, Any]:
    """Return read-only canonical review lifecycle counts."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    rows = [
        row
        for row in db.recommendations(limit=max(1, int(limit)))
        if str(row.get("recommendation_type") or "") == _RECOMMENDATION_TYPE
    ]
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "UNKNOWN").upper()
        counts[status] = counts.get(status, 0) + 1
    return {
        "count": len(rows),
        "counts": counts,
        "automatic_expiry_scope": "PROPOSED_ONLY",
        "accepted_automatic_expiry": False,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }
