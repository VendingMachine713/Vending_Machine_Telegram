from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .intelligence_audit import AuditQuery, query_intelligence_events
from .intelligence_trust import canonical_entity_parts
from .paths import project_root

_SOURCE = "Universal_Search"
_MEMBER_EVENT = "intelligence.observation.group_member_audit.member"
_SNAPSHOT_EVENT = "intelligence.observation.group_member_audit.snapshot"
_ALLOWED_CATEGORIES = {
    "LIKELY_HUMAN",
    "BOT_ACCOUNT",
    "DELETED",
    "UNCERTAIN",
    "KNOWN_CONTACT",
    "RESTRICTED",
}
_ALLOWED_CONFIDENCE = {
    "VERY_HIGH",
    "HIGH",
    "MEDIUM",
    "LOW",
    "INSUFFICIENT_EVIDENCE",
}
_MEMBER_KEYS = {
    "group_subject_id",
    "classification",
    "confidence_label",
    "reason_codes",
    "known_contact",
    "activity_state",
    "mutual_group_count",
    "review_required",
    "username_present",
    "profile_photo_present",
    "first_observed_at_utc",
    "last_observed_at_utc",
    "audit_id",
}
_SNAPSHOT_KEYS = {
    "audit_id",
    "visible_member_count",
    "expected_member_count",
    "coverage_percent",
    "data_freshness",
    "classification_counts",
}


def _payload(row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, False
    return (value, True) if isinstance(value, dict) else ({}, False)


def _canonical(value: Any, expected_type: str) -> str | None:
    text = str(value or "").strip()
    parts = canonical_entity_parts(text)
    if parts is None:
        return None
    namespace, entity_type, _ = parts
    return text if namespace == "telegram" and entity_type == expected_type else None


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


def _int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    return bool(value) if isinstance(value, bool) else False


def _safe_attrs(payload: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    attrs = payload.get("attributes")
    if not isinstance(attrs, dict):
        return {}
    return {key: attrs[key] for key in keys if key in attrs}


def _normalise_category(value: Any) -> str:
    category = str(value or "UNCERTAIN").strip().upper()
    return category if category in _ALLOWED_CATEGORIES else "UNCERTAIN"


def _normalise_confidence(value: Any) -> str:
    label = str(value or "INSUFFICIENT_EVIDENCE").strip().upper()
    return label if label in _ALLOWED_CONFIDENCE else "INSUFFICIENT_EVIDENCE"


def _reason_codes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value[:12]:
        text = str(item).strip().upper().replace(" ", "_")
        if text and text.replace("_", "").isalnum():
            cleaned.append(text)
    return cleaned


def _attention(group: dict[str, Any]) -> list[dict[str, Any]]:
    total = max(1, int(group["member_count"]))
    counts = group["classification_counts"]
    uncertain = int(counts.get("UNCERTAIN", 0))
    bots = int(counts.get("BOT_ACCOUNT", 0))
    deleted = int(counts.get("DELETED", 0))
    review = int(group["review_required_count"])
    items: list[dict[str, Any]] = []
    if bots / total >= 0.25:
        items.append({"severity": "HIGH", "code": "HIGH_BOT_CONCENTRATION", "count": bots})
    elif bots:
        items.append({"severity": "INFO", "code": "BOT_ACCOUNTS_PRESENT", "count": bots})
    if uncertain / total >= 0.20:
        items.append({"severity": "MEDIUM", "code": "HIGH_UNCERTAIN_SHARE", "count": uncertain})
    if deleted / total >= 0.10:
        items.append({"severity": "MEDIUM", "code": "HIGH_DELETED_SHARE", "count": deleted})
    if review:
        items.append({"severity": "MEDIUM", "code": "MEMBERS_REQUIRE_REVIEW", "count": review})
    coverage = group.get("coverage_percent")
    if coverage is not None and coverage < 80:
        items.append({"severity": "MEDIUM", "code": "LOW_AUDIT_COVERAGE", "count": None})
    if str(group.get("data_freshness") or "").upper() == "STALE":
        items.append({"severity": "MEDIUM", "code": "STALE_AUDIT", "count": None})
    return items


def group_member_audit_summary(
    *,
    root: Path | None = None,
    limit: int = 5000,
    group_limit: int = 20,
    member_limit: int = 100,
) -> dict[str, Any]:
    """Build a passive Mission Control read model for Telegram group-member audits.

    Producers may emit canonical member and snapshot observations. This layer never
    enumerates Telegram members, sends messages, creates outreach jobs, or mutates
    Relationship Manager data.
    """
    root = root or project_root()
    path = PlatformDB(root=root).path
    result: dict[str, Any] = {
        "status": "UNAVAILABLE" if not path.exists() else "NO_EVIDENCE",
        "group_count": 0,
        "audited_member_count": 0,
        "attention_group_count": 0,
        "groups": [],
        "filters": {
            "categories": sorted(_ALLOWED_CATEGORIES),
            "confidence_labels": ["VERY_HIGH", "HIGH", "MEDIUM", "LOW", "INSUFFICIENT_EVIDENCE"],
            "known_contact": [True, False],
            "review_required": [True, False],
            "activity_states": ["RECENT", "ACTIVE", "INACTIVE", "UNKNOWN"],
        },
        "operator_actions": [
            "VIEW_EVIDENCE",
            "MARK_FOR_MANUAL_REVIEW",
            "ADD_OPERATOR_NOTE",
            "OPEN_RELATIONSHIP_PROFILE",
            "EXPORT_FILTERED_RESULTS",
            "ADD_TO_APPROVED_OUTREACH_SHORTLIST",
        ],
        "bulk_message_action_available": False,
        "read_only": True,
        "automatic_outreach": False,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "external_action_authority": False,
        "malformed_events": 0,
        "noncanonical_events_ignored": 0,
    }

    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix="intelligence.observation.group_member_audit.",
            source=_SOURCE,
            limit=max(1, min(5000, int(limit))),
        ),
        root=root,
    )
    if not rows:
        return result

    latest_members: dict[tuple[str, str], dict[str, Any]] = {}
    snapshots: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        event_type = str(row.get("event_type") or "")
        payload, valid = _payload(row)
        event_id = _int(row.get("id"))
        created = _time(row.get("created_at_utc"))
        if not valid or event_id is None or not event_id or created is None:
            result["malformed_events"] += 1
            continue

        if event_type == _MEMBER_EVENT:
            member_id = _canonical(row.get("subject_id"), "user")
            attrs = _safe_attrs(payload, _MEMBER_KEYS)
            group_id = _canonical(attrs.get("group_subject_id"), "chat")
            if member_id is None or group_id is None:
                result["noncanonical_events_ignored"] += 1
                continue
            key = (group_id, member_id)
            existing = latest_members.get(key)
            if existing is not None and event_id <= existing["event_id"]:
                continue
            latest_members[key] = {
                "event_id": event_id,
                "member_subject_id": member_id,
                "group_subject_id": group_id,
                "classification": _normalise_category(attrs.get("classification")),
                "confidence_label": _normalise_confidence(attrs.get("confidence_label")),
                "reason_codes": _reason_codes(attrs.get("reason_codes")),
                "known_contact": _bool(attrs.get("known_contact")),
                "activity_state": str(attrs.get("activity_state") or "UNKNOWN").upper(),
                "mutual_group_count": _int(attrs.get("mutual_group_count")) or 0,
                "review_required": _bool(attrs.get("review_required")),
                "username_present": _bool(attrs.get("username_present")),
                "profile_photo_present": _bool(attrs.get("profile_photo_present")),
                "first_observed_at_utc": attrs.get("first_observed_at_utc"),
                "last_observed_at_utc": attrs.get("last_observed_at_utc"),
                "audit_id": str(attrs.get("audit_id") or ""),
                "evidence_created_at_utc": created.isoformat(),
            }
        elif event_type == _SNAPSHOT_EVENT:
            group_id = _canonical(row.get("subject_id"), "chat")
            attrs = _safe_attrs(payload, _SNAPSHOT_KEYS)
            if group_id is None:
                result["noncanonical_events_ignored"] += 1
                continue
            counts_raw = attrs.get("classification_counts")
            counts = {}
            if isinstance(counts_raw, dict):
                for key, value in counts_raw.items():
                    category = _normalise_category(key)
                    number = _int(value)
                    if number is not None:
                        counts[category] = number
            snapshots[group_id].append({
                "event_id": event_id,
                "audit_id": str(attrs.get("audit_id") or ""),
                "created_at_utc": created.isoformat(),
                "visible_member_count": _int(attrs.get("visible_member_count")),
                "expected_member_count": _int(attrs.get("expected_member_count")),
                "coverage_percent": _float(attrs.get("coverage_percent")),
                "data_freshness": str(attrs.get("data_freshness") or "UNKNOWN").upper(),
                "classification_counts": counts,
            })

    grouped_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (group_id, _member_id), member in latest_members.items():
        grouped_members[group_id].append(member)

    group_ids = set(grouped_members) | set(snapshots)
    groups: list[dict[str, Any]] = []
    for group_id in group_ids:
        members = grouped_members.get(group_id, [])
        members.sort(
            key=lambda x: (
                x["review_required"],
                x["classification"] == "UNCERTAIN",
                x["confidence_label"] in {"LOW", "INSUFFICIENT_EVIDENCE"},
                x["evidence_created_at_utc"],
            ),
            reverse=True,
        )
        counts = Counter(member["classification"] for member in members)
        confidence_counts = Counter(member["confidence_label"] for member in members)
        latest_snapshot = None
        history = sorted(snapshots.get(group_id, []), key=lambda x: x["event_id"], reverse=True)
        if history:
            latest_snapshot = history[0]
        group = {
            "group_subject_id": group_id,
            "member_count": len(members),
            "classification_counts": dict(sorted(counts.items())),
            "confidence_counts": dict(sorted(confidence_counts.items())),
            "known_contact_count": sum(1 for x in members if x["known_contact"]),
            "review_required_count": sum(1 for x in members if x["review_required"]),
            "coverage_percent": latest_snapshot.get("coverage_percent") if latest_snapshot else None,
            "data_freshness": latest_snapshot.get("data_freshness") if latest_snapshot else "UNKNOWN",
            "latest_audit_utc": latest_snapshot.get("created_at_utc") if latest_snapshot else (
                max((x["evidence_created_at_utc"] for x in members), default=None)
            ),
            "summary_cards": {
                "members": len(members),
                "likely_human": counts.get("LIKELY_HUMAN", 0),
                "bot_accounts": counts.get("BOT_ACCOUNT", 0),
                "deleted": counts.get("DELETED", 0),
                "uncertain": counts.get("UNCERTAIN", 0),
                "known_contacts": counts.get("KNOWN_CONTACT", 0),
                "restricted": counts.get("RESTRICTED", 0),
            },
            "members": members[: max(1, min(500, int(member_limit)))],
            "audit_history": history[:10],
        }
        group["attention"] = _attention(group)
        group["attention_count"] = len(group["attention"])
        groups.append(group)

    groups.sort(
        key=lambda x: (
            x["attention_count"],
            x["member_count"],
            str(x.get("latest_audit_utc") or ""),
        ),
        reverse=True,
    )
    result.update({
        "status": "PARTIAL" if result["malformed_events"] else "OK",
        "group_count": len(groups),
        "audited_member_count": sum(x["member_count"] for x in groups),
        "attention_group_count": sum(1 for x in groups if x["attention_count"]),
        "groups": groups[: max(1, min(100, int(group_limit)))],
    })
    return result
