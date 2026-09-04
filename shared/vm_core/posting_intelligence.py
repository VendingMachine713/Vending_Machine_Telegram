from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _resolve_bot_path, _tables
from .intelligence_trust import canonical_entity_id
from .paths import project_root

_RECENT_HOURS = 72
_TERMINAL = {"sent", "failed", "cancelled", "quarantined"}
_ACTIVE = {"pending", "retry", "processing", "sending", "uncertain"}
_FAILURE = {"failed", "quarantined"}


def _parse_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_int(value: Any, *, minimum: int = 0) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= minimum else None


def _delivery_health(*, sent: int, failed: int, uncertain: int) -> tuple[float | None, str]:
    resolved = sent + failed
    success_rate = round(sent / resolved, 4) if resolved else None
    if uncertain:
        return success_rate, "ATTENTION"
    if failed and (success_rate is None or success_rate < 0.8):
        return success_rate, "DEGRADED"
    if sent or failed:
        return success_rate, "HEALTHY"
    return success_rate, "NO_HISTORY"


def _posting_score(
    *,
    enabled: bool,
    needs_review: bool,
    quarantined: bool,
    sent: int,
    failed: int,
    uncertain: int,
    pending: int,
) -> float:
    """Return deterministic posting readiness diagnostics, never an action score."""
    score = 50.0
    score += 20.0 if enabled else -30.0
    score -= 30.0 if needs_review else 0.0
    score -= 40.0 if quarantined else 0.0
    score -= min(35.0, uncertain * 20.0)
    score -= min(25.0, failed * 5.0)
    score += min(20.0, sent * 2.0)
    score += min(10.0, pending * 1.0)
    return round(max(0.0, min(100.0, score)), 2)


def posting_intelligence_summary(
    *,
    root: Path | None = None,
    limit: int = 50,
    recent_hours: int = _RECENT_HOURS,
) -> dict[str, Any]:
    """Return a passive Brain-level view of Smart Auto Poster delivery state.

    Smart Auto Poster remains the data owner and execution authority. This projection
    opens its database read-only, returns only aggregate operational metrics, and
    converts destination group IDs to canonical IDs before they leave this module.
    It never mutates queue/campaign/destination state or creates recommendations.
    """
    root = root or project_root()
    bot_dir = root / "bots" / "Smart_Auto_Poster_V2"
    db_path = _resolve_bot_path(
        bot_dir,
        "DATABASE_PATH",
        bot_dir / "data" / "smart_autoposter.sqlite3",
    )
    result: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "database_available": False,
        "destination_count": 0,
        "destinations": [],
        "queue_counts": {},
        "campaign_count": 0,
        "active_campaign_count": 0,
        "recent_window_hours": max(1, int(recent_hours)),
        "malformed_rows": 0,
        "read_only": True,
        "content_exposed": False,
        "raw_telegram_ids_exposed": False,
        "diagnostic_only": True,
        "recommendation_created": False,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "automatic_retry": False,
        "automatic_queue_mutation": False,
        "automatic_rule_change": False,
        "external_action_authority": False,
    }
    con = _connect_readonly(db_path)
    if con is None:
        return result

    result["database_available"] = True
    try:
        tables = _tables(con)
        required = {"queue", "destinations"}
        if not required.issubset(tables):
            result["status"] = "REQUIRED_TABLES_MISSING"
            return result

        destination_rows = con.execute(
            """
            SELECT group_id,enabled,needs_review,quarantine_until,last_post_at,next_eligible_at
            FROM destinations
            """
        ).fetchall()
        queue_rows = con.execute(
            """
            SELECT id,campaign_id,group_id,lower(status) AS status,updated_at,due_at
            FROM queue
            ORDER BY id DESC
            """
        ).fetchall()

        campaign_rows = []
        if "campaigns" in tables:
            campaign_rows = con.execute(
                "SELECT campaign_id,enabled,lifecycle_state FROM campaigns"
            ).fetchall()
        result["campaign_count"] = len(campaign_rows)
        result["active_campaign_count"] = sum(
            1
            for row in campaign_rows
            if bool(row["enabled"])
            and str(row["lifecycle_state"] or "").lower() == "active"
        )

        queue_counts: dict[str, int] = defaultdict(int)
        per_destination: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "sent_recent": 0,
                "failed_recent": 0,
                "uncertain": 0,
                "pending": 0,
                "retry": 0,
                "processing": 0,
                "sending": 0,
                "campaign_ids": set(),
                "latest_queue_update": None,
            }
        )
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(recent_hours)))

        for row in queue_rows:
            group_id = str(row["group_id"] or "").strip()
            status = str(row["status"] or "").strip().lower()
            if not group_id or not status:
                result["malformed_rows"] += 1
                continue
            queue_counts[status] += 1
            item = per_destination[group_id]
            if status in _ACTIVE:
                item[status] = int(item.get(status, 0)) + 1
            updated = _parse_time(row["updated_at"])
            if updated is not None:
                current = item["latest_queue_update"]
                if current is None or updated > current:
                    item["latest_queue_update"] = updated
            campaign_id = row["campaign_id"]
            if campaign_id not in (None, ""):
                item["campaign_ids"].add(str(campaign_id))
            if updated is not None and updated >= cutoff:
                if status == "sent":
                    item["sent_recent"] += 1
                elif status in _FAILURE:
                    item["failed_recent"] += 1

        destinations: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for row in destination_rows:
            group_id = str(row["group_id"] or "").strip()
            if not group_id:
                result["malformed_rows"] += 1
                continue
            canonical_id = canonical_entity_id("chat", group_id)
            evidence = per_destination.get(group_id, {})
            enabled = bool(row["enabled"])
            needs_review = bool(row["needs_review"])
            quarantine_until = _parse_time(row["quarantine_until"])
            quarantined = quarantine_until is not None and quarantine_until > now
            sent = int(evidence.get("sent_recent", 0))
            failed = int(evidence.get("failed_recent", 0))
            uncertain = int(evidence.get("uncertain", 0))
            pending = sum(
                int(evidence.get(state, 0))
                for state in ("pending", "retry", "processing", "sending")
            )
            success_rate, delivery_health = _delivery_health(
                sent=sent,
                failed=failed,
                uncertain=uncertain,
            )
            latest_update = evidence.get("latest_queue_update")
            destinations.append(
                {
                    "canonical_subject_id": canonical_id,
                    "enabled": enabled,
                    "needs_review": needs_review,
                    "quarantined": quarantined,
                    "last_post_at": str(row["last_post_at"] or "") or None,
                    "next_eligible_at": str(row["next_eligible_at"] or "") or None,
                    "recent_sent": sent,
                    "recent_failed": failed,
                    "uncertain_queue_items": uncertain,
                    "active_queue_items": pending,
                    "delivery_success_rate": success_rate,
                    "delivery_health": delivery_health,
                    "campaign_count": len(evidence.get("campaign_ids", set())),
                    "latest_queue_update_utc": (
                        latest_update.isoformat() if isinstance(latest_update, datetime) else None
                    ),
                    "posting_readiness_score": _posting_score(
                        enabled=enabled,
                        needs_review=needs_review,
                        quarantined=quarantined,
                        sent=sent,
                        failed=failed,
                        uncertain=uncertain,
                        pending=pending,
                    ),
                    "posting_readiness_is_diagnostic_only": True,
                }
            )

        destinations.sort(
            key=lambda item: (
                bool(item["uncertain_queue_items"]),
                bool(item["needs_review"]),
                bool(item["quarantined"]),
                -float(item["posting_readiness_score"]),
                str(item["canonical_subject_id"]),
            ),
            reverse=True,
        )
        try:
            requested = int(limit)
        except (TypeError, ValueError):
            requested = 50
        result.update(
            {
                "status": "PARTIAL" if result["malformed_rows"] else "OK",
                "destination_count": len(destinations),
                "destinations": destinations[: max(1, min(500, requested))],
                "queue_counts": dict(sorted(queue_counts.items())),
            }
        )
        return result
    except Exception:
        # Operational inspection must fail closed rather than break Mission Control.
        result["status"] = "READ_ERROR"
        return result
    finally:
        con.close()
