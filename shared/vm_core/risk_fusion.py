from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .intelligence_audit import AuditQuery, query_intelligence_events
from .intelligence_trust import canonical_entity_parts
from .paths import project_root
from .posting_intelligence import posting_intelligence_summary

_GUARD_EVENT = "intelligence.signal.guard_risk_elevated"
_GUARD_SOURCE = "VM_Guard"


def _payload(row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, False
    return (value, True) if isinstance(value, dict) else ({}, False)


def _canonical_chat(value: Any) -> str | None:
    subject = str(value or "").strip()
    parts = canonical_entity_parts(subject)
    if parts is None:
        return None
    namespace, entity_type, _digest = parts
    return subject if namespace == "telegram" and entity_type == "chat" else None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _risk_level(score: float) -> str:
    if score >= 75:
        return "HIGH"
    if score >= 45:
        return "MEDIUM"
    if score > 0:
        return "LOW"
    return "NONE"


def canonical_risk_fusion_summary(
    *,
    root: Path | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Fuse canonical Guard and Posting Intelligence risk without taking action.

    The projection is passive. It never writes incidents, recommendations, rules,
    thresholds, queue state or Telegram actions. Risk is attached to canonical chat
    identities so later opportunity/decision layers can consume one shared view.
    """
    root = root or project_root()
    result: dict[str, Any] = {
        "status": "NO_EVIDENCE",
        "subject_count": 0,
        "subjects": [],
        "guard_subject_count": 0,
        "posting_subject_count": 0,
        "malformed_guard_events": 0,
        "noncanonical_guard_events_ignored": 0,
        "read_only": True,
        "diagnostic_only": True,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "automatic_threshold_change": False,
        "automatic_rule_change": False,
        "external_action_authority": False,
    }

    guard_rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_GUARD_EVENT,
            source=_GUARD_SOURCE,
            subject_type="chat",
            limit=max(1, min(5000, int(limit))),
        ),
        root=root,
    )
    latest_guard: dict[str, dict[str, Any]] = {}
    for row in guard_rows:
        if str(row.get("event_type") or "") != _GUARD_EVENT:
            continue
        subject = _canonical_chat(row.get("subject_id"))
        if subject is None:
            result["noncanonical_guard_events_ignored"] += 1
            continue
        payload, valid = _payload(row)
        attributes = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
        score = _safe_float(attributes.get("score"))
        try:
            event_id = int(row.get("id"))
        except (TypeError, ValueError):
            event_id = 0
        if not valid or event_id <= 0 or score is None:
            result["malformed_guard_events"] += 1
            continue
        score = max(0.0, min(100.0, score))
        current = latest_guard.get(subject)
        if current is None or event_id > int(current["event_id"]):
            latest_guard[subject] = {
                "event_id": event_id,
                "score": score,
                "created_at_utc": str(row.get("created_at_utc") or "") or None,
            }

    posting = posting_intelligence_summary(root=root, limit=max(1, min(500, int(limit))))
    posting_by_subject = {
        str(row["canonical_subject_id"]): row
        for row in posting.get("destinations", [])
        if row.get("canonical_subject_id")
    }

    result["guard_subject_count"] = len(latest_guard)
    result["posting_subject_count"] = len(posting_by_subject)
    subjects = sorted(set(latest_guard) | set(posting_by_subject))
    fused: list[dict[str, Any]] = []

    for subject in subjects:
        guard = latest_guard.get(subject)
        post = posting_by_subject.get(subject)
        guard_score = float(guard["score"]) if guard is not None else 0.0

        posting_score = 0.0
        posting_reasons: list[str] = []
        if post is not None:
            uncertain = int(post.get("uncertain_queue_items") or 0)
            failed = int(post.get("recent_failed") or 0)
            if uncertain:
                posting_score = max(posting_score, min(100.0, 70.0 + uncertain * 10.0))
                posting_reasons.append("uncertain_delivery")
            if failed:
                posting_score = max(posting_score, min(100.0, 35.0 + failed * 8.0))
                posting_reasons.append("recent_failures")
            if bool(post.get("needs_review")):
                posting_score = max(posting_score, 60.0)
                posting_reasons.append("destination_needs_review")
            if bool(post.get("quarantined")):
                posting_score = max(posting_score, 85.0)
                posting_reasons.append("destination_quarantined")

        fused_score = round(max(guard_score, posting_score), 2)
        reasons: list[str] = []
        if guard_score > 0:
            reasons.append("guard_risk")
        reasons.extend(posting_reasons)
        fused.append(
            {
                "canonical_subject_id": subject,
                "risk_score": fused_score,
                "risk_level": _risk_level(fused_score),
                "guard_risk_score": round(guard_score, 2),
                "posting_risk_score": round(posting_score, 2),
                "risk_reasons": reasons,
                "guard_evidence_event_id": guard.get("event_id") if guard else None,
                "posting_evidence_available": post is not None,
                "review_required": fused_score >= 45.0,
                "high_risk": fused_score >= 75.0,
                "diagnostic_only": True,
                "automatic_suppression": False,
                "automatic_execution": False,
            }
        )

    fused.sort(
        key=lambda row: (
            -float(row["risk_score"]),
            str(row["canonical_subject_id"]),
        )
    )
    result.update(
        {
            "status": (
                "PARTIAL" if result["malformed_guard_events"] else "OK"
            ) if fused else "NO_EVIDENCE",
            "subject_count": len(fused),
            "subjects": fused[: max(1, min(500, int(limit)))],
        }
    )
    return result
