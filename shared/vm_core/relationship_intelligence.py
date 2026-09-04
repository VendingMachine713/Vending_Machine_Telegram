from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .intelligence_audit import AuditQuery, query_intelligence_events
from .intelligence_trust import canonical_entity_parts
from .paths import project_root


_SOURCE = "VM_Relationship_Manager"
_SIGNAL_TYPES = {
    "intelligence.signal.relationship_dormant_presence": "dormant",
    "intelligence.signal.relationship_cooling_presence": "cooling",
    "intelligence.signal.business_reload_opportunity": "reload",
    "intelligence.signal.business_dormant_client_opportunity": "dormant_client",
}
_SAFE_PROFILE_KEYS = {
    "relationship_type",
    "lifecycle_stage",
    "relationship_score",
    "trust_score",
    "days_overdue",
    "group_interactions",
    "group_last_seen",
    "transaction_count",
    "total_quantity",
    "product_count",
    "last_business_at",
    "available_at",
    "days_since_last_business",
    "days_inactive",
    "inactive_threshold_days",
}


def _payload(row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, False
    return (value, True) if isinstance(value, dict) else ({}, False)


def _canonical_chat_subject(value: Any) -> str | None:
    subject = str(value or "").strip()
    parts = canonical_entity_parts(subject)
    if parts is None:
        return None
    namespace, entity_type, _digest = parts
    return subject if namespace == "telegram" and entity_type == "chat" else None


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _as_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        return {}
    return {key: attributes[key] for key in _SAFE_PROFILE_KEYS if key in attributes}


def _attention_score(signals: dict[str, dict[str, Any]], attributes: dict[str, Any]) -> float:
    """Return explainable relationship attention, not an action/opportunity score."""
    score = 0.0
    if "dormant" in signals:
        score += 40.0
    elif "cooling" in signals:
        score += 25.0
    if "reload" in signals:
        score += 20.0
    if "dormant_client" in signals:
        score += 20.0

    relationship_score = _as_float(attributes.get("relationship_score"))
    if relationship_score is not None:
        score += max(0.0, min(15.0, (50.0 - relationship_score) * 0.3))
    days_overdue = _as_float(attributes.get("days_overdue"))
    if days_overdue is not None:
        score += max(0.0, min(10.0, days_overdue / 3.0))
    return round(min(100.0, score), 2)


def relationship_intelligence_summary(
    *,
    root: Path | None = None,
    limit: int = 1000,
    profile_limit: int = 50,
) -> dict[str, Any]:
    """Build a passive Brain-level relationship read model from canonical signals.

    This function never writes events or recommendations. It consumes only canonical
    Relationship Manager signals already present in the shared event ledger and
    returns curated fields suitable for Mission Control and later shared Brain layers.
    """
    root = root or project_root()
    db_path = PlatformDB(root=root).path
    result: dict[str, Any] = {
        "status": "UNAVAILABLE" if not db_path.exists() else "NO_EVIDENCE",
        "profile_count": 0,
        "profiles": [],
        "state_counts": {},
        "signal_counts": {},
        "malformed_events": 0,
        "noncanonical_events_ignored": 0,
        "read_only": True,
        "diagnostic_attention_only": True,
        "recommendation_created": False,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "automatic_rule_change": False,
        "external_action_authority": False,
    }
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix="intelligence.signal.",
            source=_SOURCE,
            subject_type="chat",
            limit=max(1, min(5000, int(limit))),
        ),
        root=root,
    )
    eligible = [row for row in rows if str(row.get("event_type") or "") in _SIGNAL_TYPES]
    if not eligible:
        return result

    latest: dict[str, dict[str, dict[str, Any]]] = {}
    signal_counts: dict[str, int] = {}
    for row in eligible:
        event_type = str(row.get("event_type") or "")
        signal_name = _SIGNAL_TYPES[event_type]
        subject = _canonical_chat_subject(row.get("subject_id"))
        if subject is None:
            result["noncanonical_events_ignored"] += 1
            continue
        payload, valid = _payload(row)
        event_id = _as_int(row.get("id"))
        timestamp = _parse_time(row.get("created_at_utc"))
        if not valid or event_id is None or event_id <= 0 or timestamp is None:
            result["malformed_events"] += 1
            continue
        signal_counts[signal_name] = signal_counts.get(signal_name, 0) + 1
        subject_signals = latest.setdefault(subject, {})
        existing = subject_signals.get(signal_name)
        if existing is None or event_id > int(existing["event_id"]):
            subject_signals[signal_name] = {
                "event_id": event_id,
                "event_type": event_type,
                "created_at_utc": timestamp.isoformat(),
                "confidence": _as_float(payload.get("confidence")),
                "attributes": _safe_attributes(payload),
            }

    profiles: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    for subject, signals in latest.items():
        if not signals:
            continue
        merged_attributes: dict[str, Any] = {}
        ordered = sorted(signals.values(), key=lambda item: int(item["event_id"]))
        for signal in ordered:
            merged_attributes.update(signal["attributes"])

        if "dormant" in signals:
            state = "DORMANT"
        elif "cooling" in signals:
            state = "COOLING"
        elif "dormant_client" in signals:
            state = "DORMANT_CLIENT"
        elif "reload" in signals:
            state = "BUSINESS_ACTIVE"
        else:
            state = "OBSERVED"
        state_counts[state] = state_counts.get(state, 0) + 1

        confidence_values = [
            float(signal["confidence"])
            for signal in signals.values()
            if signal["confidence"] is not None
        ]
        latest_signal = max(ordered, key=lambda item: int(item["event_id"]))
        evidence_event_ids = sorted(int(signal["event_id"]) for signal in signals.values())
        profiles.append(
            {
                "canonical_subject_id": subject,
                "relationship_state": state,
                "relationship_type": merged_attributes.get("relationship_type"),
                "lifecycle_stage": merged_attributes.get("lifecycle_stage"),
                "relationship_score": _as_float(merged_attributes.get("relationship_score")),
                "trust_score": _as_float(merged_attributes.get("trust_score")),
                "days_overdue": _as_float(merged_attributes.get("days_overdue")),
                "days_inactive": _as_float(merged_attributes.get("days_inactive")),
                "days_since_last_business": _as_float(merged_attributes.get("days_since_last_business")),
                "group_interactions": _as_int(merged_attributes.get("group_interactions")),
                "transaction_count": _as_int(merged_attributes.get("transaction_count")),
                "business_reload_signal": "reload" in signals,
                "dormant_client_signal": "dormant_client" in signals,
                "signal_types": sorted(signals),
                "evidence_event_ids": evidence_event_ids,
                "evidence_count": len(evidence_event_ids),
                "mean_signal_confidence": (
                    round(sum(confidence_values) / len(confidence_values), 4)
                    if confidence_values else None
                ),
                "latest_evidence_utc": latest_signal["created_at_utc"],
                "relationship_attention_score": _attention_score(signals, merged_attributes),
                "attention_is_diagnostic_only": True,
            }
        )

    profiles.sort(
        key=lambda row: (
            float(row["relationship_attention_score"]),
            str(row["latest_evidence_utc"]),
            str(row["canonical_subject_id"]),
        ),
        reverse=True,
    )
    try:
        requested_profile_limit = int(profile_limit)
    except (TypeError, ValueError):
        requested_profile_limit = 50
    result.update(
        {
            "status": "PARTIAL" if result["malformed_events"] else "OK",
            "profile_count": len(profiles),
            "profiles": profiles[: max(1, min(500, requested_profile_limit))],
            "state_counts": dict(sorted(state_counts.items())),
            "signal_counts": dict(sorted(signal_counts.items())),
        }
    )
    return result
