from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .db import Database, utcnow


_EXACT_TITLE_PRIORITY = {
    "general": 100,
    "advertising": 95,
    "advertisements": 95,
    "marketplace": 90,
    "buy & sell": 90,
    "buy and sell": 90,
    "promotions": 85,
    "promo": 85,
    "main": 80,
}


def _clean_title(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalise_topic(value: Any) -> dict[str, Any] | None:
    """Return a bounded topic record or None for malformed/deleted records."""
    if not isinstance(value, dict):
        return None
    try:
        topic_id = int(value.get("topic_id"))
    except (TypeError, ValueError):
        return None
    if topic_id <= 0 or bool(value.get("deleted")):
        return None
    title = _clean_title(value.get("title"))[:200]
    closed = bool(value.get("closed"))
    hidden = bool(value.get("hidden"))
    score = -1000 if closed or hidden else _EXACT_TITLE_PRIORITY.get(title.casefold(), 0)
    reason = "closed_or_hidden" if closed or hidden else (
        f"exact:{title.casefold()}" if score else "available"
    )
    return {
        "topic_id": topic_id,
        "title": title,
        "closed": closed,
        "hidden": hidden,
        "pinned": bool(value.get("pinned")),
        "selection_score": score,
        "selection_reason": reason,
    }


def select_topic_route(
    topics: Iterable[dict[str, Any]],
    current_topic_id: int | None = None,
) -> tuple[int | None, str]:
    """Select only an unambiguous route; never guess between equivalent topics."""
    usable = [row for row in topics if not row.get("closed") and not row.get("hidden")]
    if current_topic_id is not None:
        for row in usable:
            if int(row["topic_id"]) == int(current_topic_id):
                return int(current_topic_id), "preserve_existing"
    if len(usable) == 1:
        return int(usable[0]["topic_id"]), "only_usable_topic"
    ranked = sorted(usable, key=lambda row: int(row.get("selection_score") or 0), reverse=True)
    if ranked:
        best = int(ranked[0].get("selection_score") or 0)
        tied = [row for row in ranked if int(row.get("selection_score") or 0) == best]
        if best > 0 and len(tied) == 1:
            return int(ranked[0]["topic_id"]), str(ranked[0].get("selection_reason") or "exact_title")
    return None, "topic_selection_required"


async def sync_forum_topics(db: Database, pool, auth: dict[str, Any]) -> dict[str, Any]:
    """Discover and persist topic visibility without sending Telegram messages."""
    with db.connect() as con:
        destinations = [
            dict(row)
            for row in con.execute(
                "SELECT group_id,topic_id,primary_access,secondary_access "
                "FROM destinations WHERE forum=1 ORDER BY group_id"
            ).fetchall()
        ]

    result: dict[str, Any] = {
        "forum_destinations": len(destinations),
        "groups_scanned": 0,
        "account_scans": 0,
        "topics_visible": 0,
        "routes_ready": 0,
        "routes_requiring_review": 0,
        "scan_errors": 0,
        "read_only_telegram": True,
        "automatic_send": False,
    }
    now = utcnow()
    for destination in destinations:
        group_id = int(destination["group_id"])
        merged: dict[int, dict[str, Any]] = {}
        scanned_accounts: list[str] = []
        for account_key in ("primary", "secondary"):
            if not auth.get(account_key, {}).get("authorized"):
                continue
            if not int(destination.get(f"{account_key}_access") or 0):
                continue
            try:
                raw_topics = await pool.forum_topics(account_key, group_id)
            except Exception:
                result["scan_errors"] += 1
                continue
            scanned_accounts.append(account_key)
            result["account_scans"] += 1
            for raw in raw_topics or []:
                topic = normalise_topic(raw)
                if topic is None:
                    continue
                row = merged.setdefault(
                    int(topic["topic_id"]),
                    {**topic, "primary_access": 0, "secondary_access": 0},
                )
                row[f"{account_key}_access"] = 1

        if not scanned_accounts:
            continue
        result["groups_scanned"] += 1
        result["topics_visible"] += len(merged)
        selected, selection_reason = select_topic_route(
            merged.values(), destination.get("topic_id")
        )
        with db.connect() as con:
            for account_key in scanned_accounts:
                con.execute(
                    f"UPDATE destination_topics SET {account_key}_access=0,updated_at=? WHERE group_id=?",
                    (now, group_id),
                )
            for topic in merged.values():
                con.execute(
                    """INSERT INTO destination_topics(
                           group_id,topic_id,title,closed,hidden,pinned,
                           primary_access,secondary_access,preferred,enabled,
                           selection_score,selection_reason,last_seen_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(group_id,topic_id) DO UPDATE SET
                           title=excluded.title,closed=excluded.closed,hidden=excluded.hidden,
                           pinned=excluded.pinned,primary_access=MAX(destination_topics.primary_access,excluded.primary_access),
                           secondary_access=MAX(destination_topics.secondary_access,excluded.secondary_access),
                           selection_score=excluded.selection_score,selection_reason=excluded.selection_reason,
                           last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at""",
                    (
                        group_id,
                        topic["topic_id"],
                        topic["title"],
                        int(topic["closed"]),
                        int(topic["hidden"]),
                        int(topic["pinned"]),
                        int(topic["primary_access"]),
                        int(topic["secondary_access"]),
                        0,
                        int(not topic["closed"] and not topic["hidden"]),
                        topic["selection_score"],
                        topic["selection_reason"],
                        now,
                        now,
                    ),
                )
            con.execute(
                """UPDATE destination_topics
                   SET enabled=CASE WHEN closed=0 AND hidden=0 AND (primary_access=1 OR secondary_access=1)
                                    THEN 1 ELSE 0 END,
                       preferred=CASE WHEN topic_id=? THEN 1 ELSE 0 END,
                       updated_at=?
                   WHERE group_id=?""",
                (selected, now, group_id),
            )
            if selected is None:
                con.execute(
                    "UPDATE destinations SET topic_id=NULL,needs_review=1,updated_at=? WHERE group_id=?",
                    (now, group_id),
                )
                result["routes_requiring_review"] += 1
            else:
                con.execute(
                    "UPDATE destinations SET topic_id=?,updated_at=? WHERE group_id=?",
                    (selected, now, group_id),
                )
                result["routes_ready"] += 1

    db.event(
        "INFO",
        "forum_topic_sync",
        "Passive forum topic synchronization complete",
        details=str({key: value for key, value in result.items() if key != "automatic_send"}),
    )
    return result


def topic_route_preview(db: Database) -> dict[str, Any]:
    """Return a local, no-send preview of every forum destination route."""
    with db.connect() as con:
        destinations = con.execute(
            """SELECT group_id,group_name,topic_id,preferred_account,enabled,needs_review
               FROM destinations WHERE forum=1 ORDER BY group_name,group_id"""
        ).fetchall()
        rows: list[dict[str, Any]] = []
        for destination in destinations:
            topics = con.execute(
                "SELECT * FROM destination_topics WHERE group_id=? ORDER BY preferred DESC,selection_score DESC,title,topic_id",
                (destination["group_id"],),
            ).fetchall()
            selected = next(
                (row for row in topics if destination["topic_id"] is not None and int(row["topic_id"]) == int(destination["topic_id"])),
                None,
            )
            preferred_account = str(destination["preferred_account"] or "primary")
            status = "READY"
            reason = "selected_topic_visible_to_required_accounts"
            if destination["topic_id"] is None:
                status = "REVIEW_REQUIRED" if topics else "UNDISCOVERED"
                reason = "ambiguous_or_unselected_topic" if topics else "run_passive_scan"
            elif selected is None or not int(selected["enabled"] or 0):
                status, reason = "BLOCKED_TOPIC_UNAVAILABLE", "selected_topic_not_currently_usable"
            elif preferred_account == "primary" and not int(selected["primary_access"] or 0):
                status, reason = "BLOCKED_ACCOUNT_ACCESS", "primary_cannot_access_selected_topic"
            elif preferred_account == "secondary" and not int(selected["secondary_access"] or 0):
                status, reason = "BLOCKED_ACCOUNT_ACCESS", "secondary_cannot_access_selected_topic"
            elif preferred_account == "both" and not (
                int(selected["primary_access"] or 0) and int(selected["secondary_access"] or 0)
            ):
                status, reason = "BLOCKED_ACCOUNT_ACCESS", "both_accounts_required_for_selected_topic"
            rows.append(
                {
                    "group_id": int(destination["group_id"]),
                    "group_name": str(destination["group_name"]),
                    "destination_enabled": bool(destination["enabled"]),
                    "needs_review": bool(destination["needs_review"]),
                    "preferred_account": preferred_account,
                    "topic_id": int(destination["topic_id"]) if destination["topic_id"] is not None else None,
                    "topic_title": str(selected["title"]) if selected is not None else None,
                    "primary_access": bool(selected["primary_access"]) if selected is not None else False,
                    "secondary_access": bool(selected["secondary_access"]) if selected is not None else False,
                    "visible_topics": len(topics),
                    "status": status,
                    "reason": reason,
                }
            )
    counts = Counter(row["status"] for row in rows)
    return {
        "read_only": True,
        "telegram_mutations": False,
        "automatic_send": False,
        "summary": {"forum_destinations": len(rows), **dict(sorted(counts.items()))},
        "routes": rows,
    }
