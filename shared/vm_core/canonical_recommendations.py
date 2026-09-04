from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .canonical_readiness import canonical_recommendation_readiness
from .db import PlatformDB
from .intelligence_audit import AuditQuery, query_intelligence_events
from .paths import project_root


_INFERENCE_TYPE = "intelligence.inference.relationship_reengagement_opportunity"
_RECOMMENDATION_TYPE = "canonical_relationship_reengagement_review"
_RULE_ID = "canonical.relationship_reengagement.review"
_RULE_VERSION = 1


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _latest_by_subject(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        subject = str(row.get("subject_id") or "").strip()
        if not subject:
            continue
        current = latest.get(subject)
        if current is None or int(row.get("id") or 0) > int(current.get("id") or 0):
            latest[subject] = row
    return latest


def _recommendation_key(subject_id: str, support_signature: str) -> str:
    body = f"{subject_id}:{support_signature}".encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()[:24]
    return f"canonical:reengagement-review:{digest}"


def _existing_recommendation(db: PlatformDB, recommendation_key: str) -> dict[str, Any] | None:
    with db.connect() as con:
        row = con.execute(
            "SELECT * FROM intelligence_recommendations WHERE recommendation_key=?",
            (recommendation_key,),
        ).fetchone()
    return dict(row) if row is not None else None


def _latest_expired_predecessor(
    db: PlatformDB,
    *,
    subject_id: str,
    replacement_key: str,
) -> dict[str, Any] | None:
    """Return the newest expired canonical review for the subject, if any.

    Terminal predecessor rows are not modified. Lineage is attached to the new
    proposal and written as a separate audit event.
    """
    with db.connect() as con:
        row = con.execute(
            """
            SELECT * FROM intelligence_recommendations
            WHERE recommendation_type=? AND subject_type='chat' AND subject_id=?
              AND status='EXPIRED' AND recommendation_key<>?
            ORDER BY id DESC LIMIT 1
            """,
            (_RECOMMENDATION_TYPE, subject_id, replacement_key),
        ).fetchone()
    return dict(row) if row is not None else None


def propose_canonical_reengagement_reviews(
    *,
    root: Path | None = None,
    minimum_opportunity_score: float = 60.0,
    limit: int = 5000,
) -> dict[str, Any]:
    """Construct operator-review recommendations from mature canonical inferences.

    This is the first persistence step after the canonical shadow/readiness gates. It
    may create or refresh PROPOSED recommendation metadata only. It never accepts a
    recommendation, sends Telegram messages, schedules work, or grants an executor
    action authority.
    """
    root = root or project_root()
    readiness = canonical_recommendation_readiness(root=root)
    result: dict[str, Any] = {
        "readiness_status": readiness.status,
        "considered": 0,
        "created": 0,
        "refreshed": 0,
        "supersession_links": 0,
        "skipped_not_ready": 0,
        "skipped_suppressed": 0,
        "skipped_low_score": 0,
        "invalid": 0,
        "recommendation_type": _RECOMMENDATION_TYPE,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }
    if not readiness.ready_for_recommendation_development:
        result["skipped_not_ready"] = 1
        return result

    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_INFERENCE_TYPE,
            source="vm_core",
            subject_type="chat",
            limit=max(1, int(limit)),
        ),
        root=root,
    )
    latest = _latest_by_subject(rows)
    if not latest:
        return result

    db = PlatformDB(root=root)
    db.init()
    minimum = max(0.0, min(100.0, float(minimum_opportunity_score)))

    for subject_id, row in sorted(latest.items()):
        result["considered"] += 1
        payload = _payload(row)
        attributes = payload.get("attributes") if isinstance(payload, dict) else None
        if not isinstance(attributes, dict):
            result["invalid"] += 1
            continue
        if bool(attributes.get("suppressed")):
            result["skipped_suppressed"] += 1
            continue

        try:
            inference_event_id = int(row.get("id") or 0)
            opportunity_score = float(attributes.get("opportunity_score"))
            confidence = float(payload.get("confidence"))
        except (TypeError, ValueError):
            result["invalid"] += 1
            continue
        support_signature = str(attributes.get("support_signature") or "").strip()
        if inference_event_id <= 0 or not support_signature:
            result["invalid"] += 1
            continue
        if opportunity_score < minimum:
            result["skipped_low_score"] += 1
            continue

        risk_assessed = bool(attributes.get("guard_evidence_recent"))
        try:
            observed_guard_risk = float(attributes.get("guard_risk_score") or 0.0)
        except (TypeError, ValueError):
            observed_guard_risk = 0.0
        risk_score = max(0.0, min(100.0, observed_guard_risk if risk_assessed else 50.0))
        priority = max(0.0, min(100.0, opportunity_score))
        recommendation_key = _recommendation_key(subject_id, support_signature)
        existed = _existing_recommendation(db, recommendation_key) is not None
        predecessor = None if existed else _latest_expired_predecessor(
            db,
            subject_id=subject_id,
            replacement_key=recommendation_key,
        )
        evidence = {
            "canonical_inference_event_id": inference_event_id,
            "support_signature": support_signature,
            "canonical_readiness_status": readiness.status,
            "canonical_evidence_health": readiness.evidence_health_status,
            "canonical_calibration_status": readiness.calibration_status,
            "risk_score": risk_score,
            "risk_assessed": risk_assessed,
            "urgency_score": priority,
            "opportunity_score": priority,
            "estimated_value_score": priority,
            "effort_score": 30.0,
            "recommendation_created_from_canonical_inference": True,
            "operator_review_required": True,
            "automatic_acceptance": False,
            "automatic_execution": False,
            "external_action_authority": False,
        }
        if predecessor is not None:
            evidence.update(
                {
                    "supersedes_recommendation_id": int(predecessor["id"]),
                    "supersedes_recommendation_key": str(predecessor["recommendation_key"]),
                    "supersession_reason": "new_canonical_evidence_after_expiry",
                }
            )
        recommendation_id = db.upsert_recommendation(
            recommendation_key,
            _RECOMMENDATION_TYPE,
            "Review whether this dormant relationship should be re-engaged",
            str(payload.get("rationale") or "Canonical relationship and activity evidence indicates a review opportunity."),
            rule_id=_RULE_ID,
            rule_version=_RULE_VERSION,
            subject_type="chat",
            subject_id=subject_id,
            priority=priority,
            confidence=max(0.0, min(1.0, confidence)),
            evidence=evidence,
            status="PROPOSED",
        )
        if existed:
            result["refreshed"] += 1
            continue

        proposal_evidence = {
            "canonical_inference_event_id": inference_event_id,
            "support_signature": support_signature,
            "rule_id": _RULE_ID,
            "rule_version": _RULE_VERSION,
        }
        if predecessor is not None:
            proposal_evidence.update(
                {
                    "supersedes_recommendation_id": int(predecessor["id"]),
                    "supersedes_recommendation_key": str(predecessor["recommendation_key"]),
                }
            )
        db.add_event(
            "recommendation.proposed",
            "vm_core.canonical_recommendations",
            {
                "recommendation_key": recommendation_key,
                "recommendation_type": _RECOMMENDATION_TYPE,
                "inference_event_id": inference_event_id,
                "operator_review_required": True,
                "automatic_acceptance": False,
                "automatic_execution": False,
            },
            subject_type="chat",
            subject_id=subject_id,
            correlation_id=f"recommendation:{recommendation_id}",
            evidence=proposal_evidence,
        )
        if predecessor is not None:
            db.add_event(
                "recommendation.supersedes",
                "vm_core.canonical_recommendations",
                {
                    "predecessor_recommendation_key": str(predecessor["recommendation_key"]),
                    "replacement_recommendation_key": recommendation_key,
                    "reason": "new_canonical_evidence_after_expiry",
                    "automatic_acceptance": False,
                    "automatic_execution": False,
                },
                subject_type="chat",
                subject_id=subject_id,
                correlation_id=f"recommendation:{recommendation_id}",
                evidence={
                    "predecessor_recommendation_id": int(predecessor["id"]),
                    "replacement_recommendation_id": recommendation_id,
                    "canonical_inference_event_id": inference_event_id,
                    "support_signature": support_signature,
                },
            )
            result["supersession_links"] += 1
        result["created"] += 1
    return result


def canonical_recommendation_summary(*, root: Path | None = None, limit: int = 50) -> dict[str, Any]:
    """Return the operator-visible state of canonical review recommendations."""
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
        "recommendations": rows,
        "operator_review_required": True,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }
