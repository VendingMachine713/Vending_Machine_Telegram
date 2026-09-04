from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .intelligence_audit import AuditQuery, query_intelligence_events
from .intelligence_contracts import EvidenceRef, IntelligenceKind, IntelligenceRecord
from .intelligence_trust import canonical_entity_id, source_trust
from .paths import project_root
from .publisher import BotEventPublisher


_SIGNAL_SOURCES: dict[str, str] = {
    "relationship_dormant_presence": "VM_Relationship_Manager",
    "relationship_cooling_presence": "VM_Relationship_Manager",
    "search_activity_spike": "Universal_Search",
    "guard_risk_elevated": "VM_Guard",
}

_HALF_LIFE_SECONDS: dict[str, float] = {
    "relationship_dormant_presence": 7 * 24 * 3600,
    "relationship_cooling_presence": 7 * 24 * 3600,
    "search_activity_spike": 24 * 3600,
    "guard_risk_elevated": 6 * 3600,
}

_POLARITY: dict[str, str] = {
    "relationship_dormant_presence": "negative",
    "relationship_cooling_presence": "negative",
    "search_activity_spike": "positive",
    "guard_risk_elevated": "negative",
}

_SAFE_EVIDENCE_KEYS = {
    "relationship_type",
    "lifecycle_stage",
    "relationship_score",
    "trust_score",
    "days_overdue",
    "group_interactions",
    "group_last_seen",
    "recent_24h_messages",
    "baseline_daily_messages",
    "recent_24h_ads",
    "ratio",
    "window_hours",
    "baseline_days",
}


def _semantic_signature(row: dict[str, Any]) -> str:
    body = {
        "signal_type": row.get("signal_type"),
        "subject_type": row.get("subject_type"),
        "subject_id": row.get("subject_id"),
        "score": row.get("score"),
        "confidence": row.get("confidence"),
        "rationale": row.get("rationale"),
        "evidence_json": row.get("evidence_json"),
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reference_hash(signal_key: str) -> str:
    digest = hashlib.sha256(signal_key.encode("utf-8")).hexdigest()[:20]
    return f"legacy_signal:{digest}"


def _safe_evidence(row: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = json.loads(row.get("evidence_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in sorted(_SAFE_EVIDENCE_KEYS) if key in raw}


def _already_published(
    *,
    root: Path,
    source: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    signature: str,
) -> bool:
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=event_type,
            source=source,
            subject_type=subject_type,
            subject_id=subject_id,
            limit=20,
        ),
        root=root,
    )
    for row in rows:
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        attributes = payload.get("attributes") if isinstance(payload, dict) else None
        if isinstance(attributes, dict) and attributes.get("bridge_signature") == signature:
            return True
    return False


def canonical_record_from_legacy_signal(row: dict[str, Any]) -> IntelligenceRecord | None:
    """Translate one supported legacy chat signal into the canonical Trust Layer contract."""
    signal_type = str(row.get("signal_type") or "")
    source = _SIGNAL_SOURCES.get(signal_type)
    subject_type = str(row.get("subject_type") or "").strip().lower()
    subject_id = str(row.get("subject_id") or "").strip()
    observed_at = str(row.get("updated_at_utc") or "").strip()
    if source is None or subject_type != "chat" or not subject_id or not observed_at:
        return None

    canonical_subject = canonical_entity_id("chat", subject_id)
    safe_evidence = _safe_evidence(row)
    signature = _semantic_signature(row)
    evidence = EvidenceRef(
        source=source,
        observed_at_utc=observed_at,
        confidence=float(row.get("confidence") or 0.0),
        source_trust=source_trust(source),
        reference=_reference_hash(str(row.get("signal_key") or signal_type)),
        attributes=safe_evidence,
    )
    return IntelligenceRecord.from_evidence(
        kind=IntelligenceKind.SIGNAL,
        record_type=signal_type,
        source=source,
        subject_type="chat",
        subject_id=canonical_subject,
        rationale=str(row.get("rationale") or signal_type),
        evidence=[evidence],
        half_life_seconds=_HALF_LIFE_SECONDS[signal_type],
        attributes={
            "legacy_bridge": True,
            "bridge_signature": signature,
            "score": float(row.get("score") or 0.0),
            "polarity": _POLARITY[signal_type],
            **safe_evidence,
        },
    )


def bridge_legacy_signals(*, root: Path | None = None, limit: int = 1000) -> dict[str, int]:
    """Publish selected legacy signals canonically while preserving legacy tables unchanged."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    rows = db.signals(limit=max(1, int(limit)), status="ACTIVE")
    result = {"eligible": 0, "published": 0, "skipped_unchanged": 0, "invalid": 0}

    for row in rows:
        if str(row.get("signal_type") or "") not in _SIGNAL_SOURCES:
            continue
        result["eligible"] += 1
        record = canonical_record_from_legacy_signal(row)
        if record is None:
            result["invalid"] += 1
            continue
        signature = str(record.attributes["bridge_signature"])
        if _already_published(
            root=root,
            source=record.source,
            event_type=record.event_type,
            subject_type=record.subject_type,
            subject_id=record.subject_id,
            signature=signature,
        ):
            result["skipped_unchanged"] += 1
            continue
        publisher = BotEventPublisher(record.source, root)
        if publisher.intelligence(record) is not None:
            result["published"] += 1
        else:
            result["invalid"] += 1
    return result
