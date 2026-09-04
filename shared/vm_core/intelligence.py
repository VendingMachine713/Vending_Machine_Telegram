from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from .activity_adapter import collect_search_activity
from .adapters import collect_all_bot_evidence
from .db import PlatformDB
from .health import run_health
from .paths import project_root
from .relationship_adapter import collect_relationship_presence
from .workflow_evidence_adapter import collect_product_workflow_evidence

RECOMMENDATION_RULE_VERSION = 1


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


def _collect_adapters(root: Path) -> dict[str, Any]:
    collectors = {
        "bot_state": lambda: collect_all_bot_evidence(root),
        "search_activity": lambda: collect_search_activity(root),
        "relationship_presence": lambda: collect_relationship_presence(root),
        "product_workflows": lambda: collect_product_workflow_evidence(root),
    }
    out: dict[str, Any] = {}
    for name, collect in collectors.items():
        try:
            out[name] = collect()
        except Exception as exc:
            out[name] = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return out


def materialize_intelligence(root: Path | None = None, *, lookback_hours: int = 72) -> dict[str, Any]:
    """Turn raw cross-bot evidence into explainable incidents and signals.

    Bot-owned databases are read-only inputs. The shared layer may update its own
    projections but never mutates Telegram queues, relationship records or search
    indexes and never performs consequential operational actions.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    adapter_results = _collect_adapters(root)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, lookback_hours))
    events = [e for e in db.events(1000) if _parse_time(e.get("created_at_utc")) >= cutoff]

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
        else:
            db.resolve_incident(key)

    created_signals = 0
    for event in events:
        st = event.get("subject_type")
        sid = event.get("subject_id")
        severity = str(event.get("severity") or "INFO").upper()
        event_type = str(event.get("event_type") or "")
        payload = _payload(event)

        if event_type.startswith("incident.") or severity in {"ERROR", "CRITICAL"}:
            key = f"event:{event['source']}:{event_type}:{st or '-'}:{sid or '-'}"
            db.upsert_incident(
                key,
                event_type,
                event["source"],
                severity,
                str(payload.get("summary") or event_type),
                subject_type=st,
                subject_id=sid,
                evidence={"event_id": event["id"], "payload": payload},
            )

        if event_type.startswith("signal.") and st and sid:
            signal_type = event_type.removeprefix("signal.")
            try:
                score = float(payload.get("score", 50))
                confidence = float(payload.get("confidence", 0.5))
            except (TypeError, ValueError):
                score, confidence = 50.0, 0.5
            db.upsert_signal(
                f"event-signal:{event['source']}:{signal_type}:{st}:{sid}",
                signal_type,
                str(payload.get("rationale") or f"Observed {signal_type} from {event['source']}"),
                subject_type=str(st),
                subject_id=str(sid),
                score=max(0, min(100, score)),
                confidence=max(0, min(1, confidence)),
                evidence={"event_id": event["id"], "source": event["source"], "payload": payload},
            )
            created_signals += 1

        if event_type in {"campaign.delivery_failed", "incident.delivery_failed", "campaign.delivery_uncertain"}:
            destination_id = str(sid or payload.get("group_id") or "unknown")
            db.upsert_signal(
                f"delivery-risk:{destination_id}",
                "delivery_risk",
                f"Recent campaign delivery evidence requires attention: {event_type}",
                subject_type=str(st or "destination"),
                subject_id=destination_id,
                score=90 if "uncertain" in event_type else 70,
                confidence=0.95,
                evidence={"event_id": event["id"], "event_type": event_type, "payload": payload},
            )
            created_signals += 1

    # Cross-bot reasoning is performed over materialised signals rather than
    # raw payload assumptions. A dormant relationship must be explicitly mapped
    # to a chat and that same chat must have an independently measured activity
    # spike. Guard risk on the same chat lowers/suppresses the opportunity.
    signals = db.signals(2000, "ACTIVE")
    by_chat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        if signal.get("subject_type") == "chat" and signal.get("subject_id"):
            by_chat[str(signal["subject_id"])].append(signal)

    with db.connect() as con:
        con.execute("UPDATE intelligence_signals SET status='INACTIVE',updated_at_utc=? WHERE signal_key LIKE 'cross:relationship_activity:%'", (datetime.now(timezone.utc).isoformat(),))

    for chat_id, rows in by_chat.items():
        types = {str(r.get("signal_type")) for r in rows}
        dormant_rows = [r for r in rows if r.get("signal_type") == "relationship_dormant_presence"]
        activity_rows = [r for r in rows if r.get("signal_type") == "search_activity_spike"]
        guard_rows = [r for r in rows if r.get("signal_type") == "guard_risk_elevated"]
        if not dormant_rows or not activity_rows:
            continue
        guard_risk = max((float(r.get("score") or 0) for r in guard_rows), default=0.0)
        activity_score = max(float(r.get("score") or 0) for r in activity_rows)
        dormant_score = max(float(r.get("score") or 0) for r in dormant_rows)
        base_score = min(100.0, (activity_score * 0.55) + (dormant_score * 0.45))
        suppressed = guard_risk >= 60
        score = min(base_score, 40.0) if suppressed else base_score
        confidence = 0.55 if suppressed else min(
            min(float(r.get("confidence") or 0) for r in activity_rows),
            min(float(r.get("confidence") or 0) for r in dormant_rows),
        )
        rationale = "Dormant relationship presence and elevated Telegram activity coincide in the same chat."
        if suppressed:
            rationale += " VM Guard reports elevated risk, so autonomous outreach should remain suppressed."
        contact_ids: list[str] = []
        for row in dormant_rows:
            try:
                evidence = json.loads(row.get("evidence_json") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                evidence = {}
            if evidence.get("contact_id") is not None:
                contact_ids.append(str(evidence["contact_id"]))
        db.upsert_signal(
            f"cross:relationship_activity:{chat_id}",
            "relationship_activity_opportunity",
            rationale,
            subject_type="chat",
            subject_id=chat_id,
            score=score,
            confidence=confidence,
            evidence={
                "supporting_signal_ids": [r["id"] for r in dormant_rows + activity_rows + guard_rows],
                "contact_ids": sorted(set(contact_ids)),
                "guard_risk_score": guard_risk,
                "suppressed": suppressed,
            },
        )
        created_signals += 1

    recommendation_count = _materialize_recommendations(db)
    return {
        "events_considered": len(events),
        "open_incidents": len(db.incidents(500, "OPEN")),
        "active_signals": len(db.signals(500, "ACTIVE")),
        "signals_materialized_this_pass": created_signals,
        "recommendations_materialized_this_pass": recommendation_count,
        "lookback_hours": lookback_hours,
        "adapters": adapter_results,
    }


def _materialize_recommendations(db: PlatformDB) -> int:
    """Convert active signals into governed, explainable next-step proposals.

    Recommendations never execute an action. A blocked recommendation remains
    visible so operators can see both the opportunity and the policy reason
    that prevented it from progressing.
    """
    signals = db.signals(2000, "ACTIVE")
    created = 0
    active_keys: set[str] = set()
    for signal in signals:
        signal_type = str(signal.get("signal_type") or "")
        subject_type = str(signal.get("subject_type") or "unknown")
        subject_id = str(signal.get("subject_id") or "unknown")
        score = float(signal.get("score") or 0)
        confidence = float(signal.get("confidence") or 0)
        evidence = _payload(signal, "evidence_json")

        if signal_type == "relationship_activity_opportunity":
            key = f"recommendation:relationship_activity:{subject_id}"
            blocked = bool(evidence.get("suppressed"))
            db.upsert_recommendation(
                key, "relationship_review",
                "Review the linked dormant contacts and prepare a human-approved outreach plan.",
                "Relationship dormancy and elevated activity coincide in the same chat."
                + (" Elevated guard risk blocks outreach." if blocked else ""),
                rule_id="relationship_activity_review", rule_version=RECOMMENDATION_RULE_VERSION,
                subject_type=subject_type, subject_id=subject_id,
                priority=score, confidence=confidence,
                status="BLOCKED" if blocked else "PROPOSED",
                evidence={
                    "supporting_signal_id": signal["id"],
                    "supporting_signal_ids": evidence.get("supporting_signal_ids", []),
                    "contact_ids": evidence.get("contact_ids", []),
                    "guard_risk_score": evidence.get("guard_risk_score", 0),
                    "automatic_execution": False,
                },
            )
        elif signal_type == "delivery_risk" and score >= 70:
            key = f"recommendation:delivery_reconciliation:{subject_id}"
            db.upsert_recommendation(
                key, "delivery_reconciliation",
                "Run the existing safe delivery-reconciliation preview; do not retry uncertain jobs automatically.",
                "Shared evidence reports elevated or uncertain delivery risk for this destination.",
                rule_id="delivery_risk_reconciliation", rule_version=RECOMMENDATION_RULE_VERSION,
                subject_type=subject_type, subject_id=subject_id,
                priority=score, confidence=confidence, status="PROPOSED",
                evidence={
                    "supporting_signal_id": signal["id"],
                    "automatic_retry": False,
                    "automatic_execution": False,
                },
            )
        elif signal_type == "guard_risk_elevated" and score >= 60:
            key = f"recommendation:guard_review:{subject_id}"
            db.upsert_recommendation(
                key, "guard_review",
                "Review VM Guard evidence before allowing campaign or relationship actions in this chat.",
                "VM Guard reports risk at or above the shared safety threshold.",
                rule_id="guard_risk_review", rule_version=RECOMMENDATION_RULE_VERSION,
                subject_type=subject_type, subject_id=subject_id,
                priority=score, confidence=confidence, status="PROPOSED",
                evidence={"supporting_signal_id": signal["id"], "automatic_execution": False},
            )
        else:
            continue
        active_keys.add(key)
        created += 1

    # Recommendations that no longer have active evidence expire, while human
    # decisions and completed records remain immutable audit history.
    with db.connect() as con:
        rows = con.execute(
            "SELECT recommendation_key FROM intelligence_recommendations "
            "WHERE status IN ('PROPOSED','BLOCKED')"
        ).fetchall()
        stale = [str(row[0]) for row in rows if str(row[0]) not in active_keys]
        if stale:
            placeholders = ",".join("?" for _ in stale)
            con.execute(
                f"UPDATE intelligence_recommendations SET status='EXPIRED',updated_at_utc=? "
                f"WHERE recommendation_key IN ({placeholders})",
                (datetime.now(timezone.utc).isoformat(), *stale),
            )
    return created


def intelligence_summary(root: Path | None = None, *, refresh: bool = True) -> dict[str, Any]:
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    materialization = materialize_intelligence(root) if refresh else None
    incidents = db.incidents(20, "OPEN")
    signals = db.signals(20, "ACTIVE")
    recommendations = db.recommendations(20)
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
        "recommendations": recommendations,
        "recent_events": db.events(20),
        "materialization": materialization,
    }


def format_intelligence_summary(summary: dict[str, Any]) -> str:
    h = summary["platform_health"]
    incidents = summary.get("open_incidents", [])
    signals = summary.get("active_signals", [])
    recommendations = summary.get("recommendations", [])
    lines = [
        "VM INTELLIGENCE",
        f"Services healthy: {h['healthy_services']}/{h['total_services']}",
        f"Open incidents: {len(incidents)}",
        f"Active signals: {len(signals)}",
        f"Recommendations: {len(recommendations)}",
    ]
    materialization = summary.get("materialization") or {}
    adapters = materialization.get("adapters") or {}
    if adapters:
        available = 0
        total = 0
        for value in adapters.values():
            if isinstance(value, dict):
                if "available" in value:
                    total += 1
                    available += int(bool(value.get("available")))
                else:
                    for nested in value.values():
                        if isinstance(nested, dict) and "available" in nested:
                            total += 1
                            available += int(bool(nested.get("available")))
        if total:
            lines.append(f"Evidence adapters: {available}/{total} available")
    if incidents:
        lines.append("\nINCIDENTS")
        for row in incidents[:8]:
            lines.append(f"{row['severity']:<8} {row['summary']}")
    if signals:
        lines.append("\nSIGNALS")
        for row in signals[:8]:
            lines.append(f"{int(row['score']):>3}/100 {row['signal_type']} - {row['rationale']}")
    if recommendations:
        lines.append("\nRECOMMENDATIONS")
        for row in recommendations[:8]:
            lines.append(f"{row['status']:<9} {int(row['priority']):>3}/100 {row['action']}")
    if not incidents and not signals and not recommendations:
        lines.append("\nNo cross-bot incidents or intelligence signals currently require attention.")
    return "\n".join(lines)
