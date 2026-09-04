from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .group_search_intelligence import group_search_intelligence_summary
from .paths import project_root
from .relationship_intelligence import relationship_intelligence_summary

POSITIVE_SIGNAL_TYPES = {
    "relationship_momentum": 1.0,
    "relationship_attention": 0.7,
    "campaign_state": 0.5,
}
NEGATIVE_SIGNAL_TYPES = {
    "delivery_risk": 1.0,
    "delivery_failure": 0.7,
}


def _evidence(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def opportunities(root: Path | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    """Rank legacy evidence-backed opportunities without accepting or executing actions.

    This compatibility surface remains unchanged while the canonical Brain opportunity
    view is built by :func:`canonical_opportunities` below.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in db.signals(limit=max(200, limit * 10), status="ACTIVE"):
        subject_type = str(row.get("subject_type") or "")
        subject_id = str(row.get("subject_id") or "")
        if not subject_type or not subject_id:
            continue
        key = (subject_type, subject_id)
        item = grouped.setdefault(key, {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "positive": 0.0,
            "risk": 0.0,
            "confidence_weight": 0.0,
            "signals": [],
            "campaign_ids": set(),
        })
        signal_type = str(row.get("signal_type") or "")
        score = max(0.0, min(100.0, float(row.get("score") or 0)))
        confidence = max(0.0, min(1.0, float(row.get("confidence") or 0)))
        if signal_type in POSITIVE_SIGNAL_TYPES:
            item["positive"] += score * confidence * POSITIVE_SIGNAL_TYPES[signal_type]
            item["confidence_weight"] += confidence
        if signal_type in NEGATIVE_SIGNAL_TYPES:
            item["risk"] += score * confidence * NEGATIVE_SIGNAL_TYPES[signal_type]
        evidence = _evidence(row.get("evidence_json"))
        if evidence.get("campaign_id") not in (None, ""):
            item["campaign_ids"].add(str(evidence["campaign_id"]))
        item["signals"].append({
            "key": row["signal_key"],
            "type": signal_type,
            "score": score,
            "confidence": confidence,
        })

    open_incidents = db.incidents(limit=500, status="OPEN")
    incident_subjects = {
        (str(row.get("subject_type") or ""), str(row.get("subject_id") or "")): row
        for row in open_incidents if row.get("subject_type") and row.get("subject_id")
    }
    result: list[dict[str, Any]] = []
    for key, item in grouped.items():
        if item["positive"] <= 0:
            continue
        incident = incident_subjects.get(key)
        incident_penalty = 35.0 if incident and str(incident.get("severity") or "").upper() in {"ERROR", "CRITICAL"} else 15.0 if incident else 0.0
        raw = item["positive"] - item["risk"] - incident_penalty
        score = round(max(0.0, min(100.0, raw)), 2)
        confidence = round(max(0.0, min(1.0, item["confidence_weight"] / max(1, len(item["signals"])))), 3)
        blocked = bool(incident and str(incident.get("severity") or "").upper() in {"ERROR", "CRITICAL"})
        result.append({
            "subject_type": item["subject_type"],
            "subject_id": item["subject_id"],
            "opportunity_score": score,
            "confidence": confidence,
            "risk_score": round(min(100.0, item["risk"] + incident_penalty), 2),
            "blocked": blocked,
            "block_reason": str(incident.get("summary")) if blocked else None,
            "campaign_ids": sorted(item["campaign_ids"]),
            "signals": sorted(item["signals"], key=lambda row: (-row["score"], row["key"])),
            "automatic_execution": False,
        })
    result.sort(key=lambda row: (row["blocked"], -row["opportunity_score"], -row["confidence"], row["subject_type"], row["subject_id"]))
    return result[: max(1, int(limit))]


def _canonical_kind(profile: dict[str, Any], group: dict[str, Any] | None) -> str:
    if profile.get("business_reload_signal"):
        return "BUSINESS_RELOAD_REVIEW"
    if profile.get("dormant_client_signal"):
        return "DORMANT_CLIENT_REVIEW"
    state = str(profile.get("relationship_state") or "")
    if state == "DORMANT" and group is not None:
        return "REENGAGEMENT_ACTIVITY_REVIEW"
    if state == "DORMANT":
        return "DORMANT_RELATIONSHIP_REVIEW"
    if state == "COOLING" and group is not None:
        return "COOLING_ACTIVITY_REVIEW"
    return "RELATIONSHIP_REVIEW"


def _canonical_score(profile: dict[str, Any], group: dict[str, Any] | None) -> float:
    relationship = max(0.0, min(100.0, float(profile.get("relationship_attention_score") or 0.0)))
    momentum = (
        max(0.0, min(100.0, float(group.get("group_momentum_score") or 0.0)))
        if group is not None else 0.0
    )
    business_bonus = 10.0 if profile.get("business_reload_signal") else 7.0 if profile.get("dormant_client_signal") else 0.0
    cross_domain_bonus = 8.0 if group is not None else 0.0
    score = relationship * 0.62 + momentum * 0.30 + business_bonus + cross_domain_bonus
    return round(max(0.0, min(100.0, score)), 2)


def _canonical_confidence(profile: dict[str, Any], group: dict[str, Any] | None) -> float:
    values: list[float] = []
    relationship_confidence = profile.get("mean_signal_confidence")
    if relationship_confidence is not None:
        values.append(max(0.0, min(1.0, float(relationship_confidence))))
    if group is not None and group.get("confidence") is not None:
        values.append(max(0.0, min(1.0, float(group["confidence"]))))
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def canonical_opportunities(
    root: Path | None = None,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Rank canonical shared-Brain opportunity candidates without creating actions.

    This is a passive synthesis of the existing Relationship Intelligence and
    Group/Search Intelligence read models. It does not write recommendations/events,
    perform risk fusion, alter thresholds/rules, or execute Telegram/external work.
    Risk fusion is intentionally deferred to its dedicated roadmap milestone.
    """
    root = root or project_root()
    relationship = relationship_intelligence_summary(
        root=root,
        limit=max(200, limit * 20),
        profile_limit=max(200, limit * 20),
    )
    group_search = group_search_intelligence_summary(
        root=root,
        limit=max(200, limit * 20),
        group_limit=max(200, limit * 20),
    )
    groups = {
        str(row["canonical_subject_id"]): row
        for row in group_search.get("groups", [])
        if row.get("canonical_subject_id")
    }

    result: list[dict[str, Any]] = []
    for profile in relationship.get("profiles", []):
        subject = str(profile.get("canonical_subject_id") or "")
        if not subject:
            continue
        group = groups.get(subject)
        score = _canonical_score(profile, group)
        if score <= 0:
            continue
        relationship_events = [
            int(value) for value in profile.get("evidence_event_ids", [])
            if isinstance(value, int) and value > 0
        ]
        group_event = group.get("evidence_event_id") if group is not None else None
        evidence_event_ids = sorted(set(relationship_events + ([int(group_event)] if isinstance(group_event, int) and group_event > 0 else [])))
        result.append({
            "canonical_subject_id": subject,
            "opportunity_type": _canonical_kind(profile, group),
            "opportunity_score": score,
            "confidence": _canonical_confidence(profile, group),
            "relationship_state": profile.get("relationship_state"),
            "relationship_attention_score": profile.get("relationship_attention_score"),
            "group_momentum_score": group.get("group_momentum_score") if group is not None else None,
            "cross_domain_evidence": group is not None,
            "business_reload_signal": bool(profile.get("business_reload_signal")),
            "dormant_client_signal": bool(profile.get("dormant_client_signal")),
            "evidence_event_ids": evidence_event_ids,
            "evidence_count": len(evidence_event_ids),
            "risk_fusion_applied": False,
            "blocked": False,
            "block_reason": None,
            "diagnostic_candidate_only": True,
            "recommendation_created": False,
            "automatic_acceptance": False,
            "automatic_execution": False,
            "automatic_threshold_change": False,
            "automatic_rule_change": False,
            "external_action_authority": False,
        })

    result.sort(
        key=lambda row: (
            -float(row["opportunity_score"]),
            -float(row["confidence"]),
            str(row["canonical_subject_id"]),
        )
    )
    try:
        requested = int(limit)
    except (TypeError, ValueError):
        requested = 50
    return result[: max(1, min(500, requested))]


def opportunity_summary(root: Path | None = None, *, limit: int = 20) -> dict[str, Any]:
    legacy_rows = opportunities(root, limit=limit)
    canonical_rows = canonical_opportunities(root, limit=limit)
    return {
        # Backwards-compatible legacy fields.
        "count": len(legacy_rows),
        "blocked_count": sum(1 for row in legacy_rows if row["blocked"]),
        "top_opportunities": legacy_rows,
        # Shared Brain canonical opportunity view.
        "canonical_count": len(canonical_rows),
        "canonical_top_opportunities": canonical_rows,
        "canonical_cross_domain_count": sum(1 for row in canonical_rows if row["cross_domain_evidence"]),
        "canonical_risk_fusion_applied": False,
        "read_only_canonical_synthesis": True,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "automatic_threshold_change": False,
        "automatic_rule_change": False,
        "external_action_authority": False,
    }
