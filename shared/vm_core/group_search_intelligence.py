from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .intelligence_audit import AuditQuery, query_intelligence_events
from .intelligence_trust import canonical_entity_parts
from .paths import project_root


_SOURCE = "Universal_Search"
_EVENT_TYPE = "intelligence.signal.search_activity_spike"
_SAFE_KEYS = {
    "recent_24h_messages",
    "baseline_daily_messages",
    "recent_24h_ads",
    "ratio",
    "window_hours",
    "baseline_days",
    "score",
}


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


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _attributes(payload: dict[str, Any]) -> dict[str, Any]:
    attrs = payload.get("attributes")
    if not isinstance(attrs, dict):
        return {}
    return {key: attrs[key] for key in _SAFE_KEYS if key in attrs}


def _momentum_score(*, ratio: float | None, messages: int | None, ads: int | None) -> float:
    """Diagnostic group/search momentum, not an opportunity or action score."""
    score = 0.0
    if ratio is not None:
        score += min(70.0, max(0.0, (ratio - 1.0) * 25.0))
    if messages is not None:
        score += min(20.0, max(0.0, messages / 5.0))
    if messages and ads is not None:
        ad_share = ads / max(1, messages)
        score += min(10.0, max(0.0, ad_share * 20.0))
    return round(min(100.0, score), 2)


def group_search_intelligence_summary(
    *,
    root: Path | None = None,
    limit: int = 1000,
    group_limit: int = 50,
) -> dict[str, Any]:
    """Return a passive canonical view of group/search activity intelligence.

    Universal Search remains the data producer. This shared Brain layer only reads
    canonical activity-spike events and exposes aggregate counts/metrics; indexed
    message text, usernames and raw Telegram IDs are never returned.
    """
    root = root or project_root()
    path = PlatformDB(root=root).path
    result: dict[str, Any] = {
        "status": "UNAVAILABLE" if not path.exists() else "NO_EVIDENCE",
        "group_count": 0,
        "groups": [],
        "malformed_events": 0,
        "noncanonical_events_ignored": 0,
        "read_only": True,
        "content_exposed": False,
        "diagnostic_momentum_only": True,
        "recommendation_created": False,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "automatic_rule_change": False,
        "external_action_authority": False,
    }
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_EVENT_TYPE,
            source=_SOURCE,
            subject_type="chat",
            limit=max(1, min(5000, int(limit))),
        ),
        root=root,
    )
    if not rows:
        return result

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("event_type") or "") != _EVENT_TYPE:
            continue
        subject = _canonical_chat(row.get("subject_id"))
        if subject is None:
            result["noncanonical_events_ignored"] += 1
            continue
        payload, valid = _payload(row)
        timestamp = _time(row.get("created_at_utc"))
        try:
            event_id = int(row.get("id"))
        except (TypeError, ValueError):
            event_id = 0
        if not valid or timestamp is None or event_id <= 0:
            result["malformed_events"] += 1
            continue
        current = latest.get(subject)
        if current is not None and event_id <= int(current["event_id"]):
            continue
        attrs = _attributes(payload)
        latest[subject] = {
            "event_id": event_id,
            "canonical_subject_id": subject,
            "created_at_utc": timestamp.isoformat(),
            "confidence": _float(payload.get("confidence")),
            "attributes": attrs,
        }

    groups: list[dict[str, Any]] = []
    for item in latest.values():
        attrs = item["attributes"]
        recent_messages = _int(attrs.get("recent_24h_messages"))
        baseline = _float(attrs.get("baseline_daily_messages"))
        recent_ads = _int(attrs.get("recent_24h_ads"))
        ratio = _float(attrs.get("ratio"))
        if ratio is None and recent_messages is not None and baseline is not None:
            ratio = recent_messages / max(1.0, baseline)
        ad_share = (
            round(recent_ads / max(1, recent_messages), 4)
            if recent_ads is not None and recent_messages is not None
            else None
        )
        groups.append(
            {
                "canonical_subject_id": item["canonical_subject_id"],
                "evidence_event_id": item["event_id"],
                "latest_evidence_utc": item["created_at_utc"],
                "confidence": item["confidence"],
                "recent_24h_messages": recent_messages,
                "baseline_daily_messages": baseline,
                "activity_ratio": round(ratio, 4) if ratio is not None else None,
                "recent_24h_ads": recent_ads,
                "recent_ad_share": ad_share,
                "window_hours": _int(attrs.get("window_hours")),
                "baseline_days": _int(attrs.get("baseline_days")),
                "source_signal_score": _float(attrs.get("score")),
                "group_momentum_score": _momentum_score(
                    ratio=ratio,
                    messages=recent_messages,
                    ads=recent_ads,
                ),
                "momentum_is_diagnostic_only": True,
            }
        )

    groups.sort(
        key=lambda row: (
            float(row["group_momentum_score"]),
            str(row["latest_evidence_utc"]),
            str(row["canonical_subject_id"]),
        ),
        reverse=True,
    )
    try:
        requested = int(group_limit)
    except (TypeError, ValueError):
        requested = 50
    result.update(
        {
            "status": "PARTIAL" if result["malformed_events"] else "OK",
            "group_count": len(groups),
            "groups": groups[: max(1, min(500, requested))],
        }
    )
    return result
