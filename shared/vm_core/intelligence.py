from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .health import run_health
from .paths import project_root


def _payload(row: dict[str, Any], key: str = "payload_json") -> dict[str, Any]:
    try:
        value = json.loads(row.get(key) or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def materialize_intelligence(root: Path | None = None, *, lookback_hours: int = 72) -> dict[str, Any]:
    """Turn raw cross-bot evidence into explainable incidents and signals.

    Rules are intentionally conservative and evidence based. They never mutate
    bot-owned data or trigger operational actions; they only materialise shared
    intelligence for dashboards and later governed automation.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, lookback_hours))
    events = [e for e in db.events(1000) if _parse_time(e.get("created_at_utc")) >= cutoff]

    open_incidents: set[str] = set()
    for h in run_health(root):
        status = str(h.get("status", "UNKNOWN")).upper()
        key = f"health:{h['service']}"
        if status not in {"OK", "HEALTHY", "RUNNING", "ONLINE", "READY"}:
            db.upsert_incident(
                key,
                "service_health",
                "vm_core.health",
                "ERROR" if status in {"FAIL", "ERROR", "CRITICAL"} else "WARNING",
                f"{h['service']} health is {status}",
                subject_type="service",
                subject_id=h["service"],
                evidence={"health": h},
            )
            open_incidents.add(key)
        else:
            db.resolve_incident(key)

    subject_events: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        st = event.get("subject_type")
        sid = event.get("subject_id")
        if st and sid:
            subject_events[(str(st), str(sid))].append(event)

        severity = str(event.get("severity") or "INFO").upper()
        if event.get("event_type", "").startswith("incident.") or severity in {"ERROR", "CRITICAL"}:
            key = f"event:{event['source']}:{event['event_type']}:{st or '-'}:{sid or '-'}"
            payload = _payload(event)
            summary = str(payload.get("summary") or event["event_type"])
            db.upsert_incident(
                key,
                event["event_type"],
                event["source"],
                severity,
                summary,
                subject_type=st,
                subject_id=sid,
                evidence={"event_id": event["id"], "payload": payload},
            )
            open_incidents.add(key)

    created_signals = 0
    for (subject_type, subject_id), rows in subject_events.items():
        types = {str(r.get("event_type")) for r in rows}
        has_relationship = any(t in types for t in {"signal.relationship_dormant", "relationship.dormant"})
        has_activity = any(t in types for t in {"signal.search_activity_spike", "search.activity_spike"})
        has_guard_risk = any(t in types for t in {"signal.guard_risk_elevated", "guard.risk_elevated"})
        if has_relationship and has_activity:
            confidence = 0.9 if not has_guard_risk else 0.55
            score = 85 if not has_guard_risk else 45
            rationale = (
                "Relationship dormancy and increased Telegram/search activity were both observed."
                + (" VM Guard also reported elevated risk, so the opportunity is suppressed." if has_guard_risk else "")
            )
            db.upsert_signal(
                f"cross:relationship_activity:{subject_type}:{subject_id}",
                "relationship_activity_opportunity",
                rationale,
                subject_type=subject_type,
                subject_id=subject_id,
                score=score,
                confidence=confidence,
                evidence={"event_ids": [r["id"] for r in rows], "guard_risk": has_guard_risk},
            )
            created_signals += 1

    for event in events:
        et = str(event.get("event_type"))
        if et in {"campaign.delivery_failed", "incident.delivery_failed", "campaign.delivery_uncertain"}:
            payload = _payload(event)
            sid = str(event.get("subject_id") or payload.get("group_id") or "unknown")
            db.upsert_signal(
                f"delivery-risk:{sid}",
                "delivery_risk",
                f"Recent campaign delivery evidence requires attention: {et}",
                subject_type=event.get("subject_type") or "destination",
                subject_id=sid,
                score=90 if "uncertain" in et else 70,
                confidence=0.95,
                evidence={"event_id": event["id"], "event_type": et, "payload": payload},
            )
            created_signals += 1

    return {
        "events_considered": len(events),
        "open_incidents": len(db.incidents(500, "OPEN")),
        "active_signals": len(db.signals(500, "ACTIVE")),
        "signals_materialized_this_pass": created_signals,
        "lookback_hours": lookback_hours,
    }


def intelligence_summary(root: Path | None = None, *, refresh: bool = True) -> dict[str, Any]:
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    materialization = materialize_intelligence(root) if refresh else None
    incidents = db.incidents(20, "OPEN")
    signals = db.signals(20, "ACTIVE")
    health = run_health(root)
    healthy = sum(1 for h in health if str(h.get("status", "")).upper() in {"OK", "HEALTHY", "RUNNING", "ONLINE", "READY"})
    return {
        "platform_health": {
            "healthy_services": healthy,
            "total_services": len(health),
            "attention_services": len(health) - healthy,
        },
        "open_incidents": incidents,
        "active_signals": signals,
        "recent_events": db.events(20),
        "materialization": materialization,
    }


def format_intelligence_summary(summary: dict[str, Any]) -> str:
    h = summary["platform_health"]
    incidents = summary.get("open_incidents", [])
    signals = summary.get("active_signals", [])
    lines = [
        "VM INTELLIGENCE",
        f"Services healthy: {h['healthy_services']}/{h['total_services']}",
        f"Open incidents: {len(incidents)}",
        f"Active signals: {len(signals)}",
    ]
    if incidents:
        lines.append("\nINCIDENTS")
        for row in incidents[:8]:
            lines.append(f"{row['severity']:<8} {row['summary']}")
    if signals:
        lines.append("\nSIGNALS")
        for row in signals[:8]:
            lines.append(f"{int(row['score']):>3}/100 {row['signal_type']} - {row['rationale']}")
    if not incidents and not signals:
        lines.append("\nNo cross-bot incidents or intelligence signals currently require attention.")
    return "\n".join(lines)
