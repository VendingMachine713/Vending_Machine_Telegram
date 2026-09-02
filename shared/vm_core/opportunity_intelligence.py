from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .paths import project_root

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
    """Rank evidence-backed opportunities without accepting or executing actions."""
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


def opportunity_summary(root: Path | None = None, *, limit: int = 20) -> dict[str, Any]:
    rows = opportunities(root, limit=limit)
    return {
        "count": len(rows),
        "blocked_count": sum(1 for row in rows if row["blocked"]),
        "top_opportunities": rows,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }
