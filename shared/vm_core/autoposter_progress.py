from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from .adapters import _connect_readonly, _resolve_bot_path, _tables
from .paths import project_root
from .progress import ProgressEvent, ProgressLine, progress_snapshot

_TERMINAL = {"sent", "failed", "cancelled", "quarantined"}
_ACTIVE = {"pending", "retry", "processing", "sending", "uncertain"}
_WORKING = {"pending", "retry", "processing", "sending"}


def _count_statuses(con) -> dict[str, int]:
    rows = con.execute("SELECT lower(status) AS status, COUNT(*) AS n FROM queue GROUP BY lower(status)").fetchall()
    return {str(row["status"]): int(row["n"] or 0) for row in rows}


def _queue_columns(con) -> set[str]:
    return {str(row[1]) for row in con.execute("PRAGMA table_info(queue)").fetchall()}


def _latest_active(con, columns: set[str]) -> dict[str, Any] | None:
    due_expr = "q.due_at" if "due_at" in columns else "NULL AS due_at"
    row = con.execute(
        f"""
        SELECT q.id,q.campaign_id,q.group_id,q.account_key,lower(q.status) AS status,
               q.error_kind,q.last_error,q.updated_at,{due_expr},d.group_name
        FROM queue q
        LEFT JOIN destinations d ON d.group_id=q.group_id
        WHERE lower(q.status) IN ('pending','retry','processing','sending','uncertain')
        ORDER BY
          CASE lower(q.status)
            WHEN 'sending' THEN 0 WHEN 'processing' THEN 1 WHEN 'retry' THEN 2
            WHEN 'uncertain' THEN 3 ELSE 4 END,
          q.id ASC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def _parse_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    hours, minute = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minute}m" if minute else f"{hours}h"
    days, hour = divmod(hours, 24)
    return f"{days}d {hour}h" if hour else f"{days}d"


def _throughput_metrics(con, counts: dict[str, int], columns: set[str]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "queue_total": sum(counts.values()),
        "queue_terminal": sum(counts.get(state, 0) for state in _TERMINAL),
        "queue_active": sum(counts.get(state, 0) for state in _ACTIVE),
        "sent": counts.get("sent", 0),
        "uncertain": counts.get("uncertain", 0),
    }
    if "due_at" in columns:
        row = con.execute(
            "SELECT MIN(due_at) FROM queue WHERE lower(status) IN ('pending','retry','processing','sending')"
        ).fetchone()
        if row and row[0]:
            metrics["next_due"] = row[0]

    if "updated_at" not in columns:
        return metrics
    rows = con.execute(
        "SELECT updated_at FROM queue WHERE lower(status)='sent' AND updated_at IS NOT NULL ORDER BY id DESC LIMIT 20"
    ).fetchall()
    times = sorted(t for t in (_parse_time(row[0]) for row in rows) if t is not None)
    intervals = [
        (later - earlier).total_seconds()
        for earlier, later in zip(times, times[1:])
        if 0 < (later - earlier).total_seconds() <= 21600
    ]
    if intervals:
        typical = median(intervals)
        remaining = sum(counts.get(state, 0) for state in _WORKING)
        metrics["typical_send_interval"] = _format_duration(typical)
        if remaining:
            metrics["estimated_queue_eta"] = _format_duration(typical * remaining)
            metrics["eta_basis"] = f"median of {len(intervals)} recent send interval(s)"
    return metrics


def _recent_events(con, tables: set[str]) -> list[dict[str, Any]]:
    if "events" not in tables:
        return []
    rows = con.execute(
        "SELECT created_at,severity,event_type,message FROM events ORDER BY id DESC LIMIT 7"
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in reversed(rows):
        severity = str(row["severity"] or "INFO").upper()
        result.append(
            {
                "message": str(row["message"] or row["event_type"] or "event"),
                "level": severity,
                "source": f"Smart_Auto_Poster_V2/{row['event_type'] or 'event'}",
                "at": str(row["created_at"] or ""),
            }
        )
    return result


def smart_auto_poster_progress(root: Path | None = None) -> dict[str, Any]:
    """Return a read-only Smart Auto Poster snapshot for the Universal Progress Engine.

    The adapter never mutates the bot database. It derives progress only from
    explicit queue/campaign/destination state so operator visibility cannot
    change delivery behaviour.
    """
    root = root or project_root()
    bot_dir = root / "bots" / "Smart_Auto_Poster_V2"
    db_path = _resolve_bot_path(bot_dir, "DATABASE_PATH", bot_dir / "data" / "smart_autoposter.sqlite3")
    con = _connect_readonly(db_path)
    if con is None:
        return progress_snapshot(
            headline="SMART AUTO POSTER",
            overall=ProgressLine("Queue unavailable", status="DEGRADED", detail=str(db_path)),
            recovery_messages=["Smart Auto Poster database is unavailable; posting state was not inferred."],
        )

    try:
        tables = _tables(con)
        if not {"queue", "destinations"}.issubset(tables):
            return progress_snapshot(
                headline="SMART AUTO POSTER",
                overall=ProgressLine("Progress data unavailable", status="DEGRADED"),
                recovery_messages=["Required queue/destination tables are missing; no delivery assumptions were made."],
            )

        columns = _queue_columns(con)
        counts = _count_statuses(con)
        total = sum(counts.values())
        complete = sum(counts.get(state, 0) for state in _TERMINAL)
        unresolved = counts.get("uncertain", 0)
        failed = counts.get("failed", 0) + counts.get("quarantined", 0)
        active = _latest_active(con, columns)

        overall_status = "RUNNING" if any(counts.get(s, 0) for s in _ACTIVE) else "COMPLETE"
        if unresolved:
            overall_status = "ATTENTION"

        overall = ProgressLine(
            "Current posting queue",
            current=complete,
            total=total,
            status=overall_status,
            detail=(
                f"sent={counts.get('sent', 0)} pending={counts.get('pending', 0)} "
                f"retry={counts.get('retry', 0)} uncertain={unresolved} failed={failed}"
            ),
        )

        group = None
        task = None
        events = _recent_events(con, tables)
        recovery: list[str] = []

        if active:
            group_name = active.get("group_name") or str(active.get("group_id") or "unknown destination")
            status = str(active.get("status") or "unknown").upper()
            step = 1 if status in {"PROCESSING", "SENDING"} else 0
            due = f" due={active.get('due_at')}" if active.get("due_at") else ""
            group = ProgressLine(
                str(group_name), current=step, total=2, status=status,
                detail=f"campaign={active.get('campaign_id')} account={active.get('account_key') or 'unassigned'}{due}",
            )
            task = ProgressLine(
                f"Queue job #{active.get('id')}", current=step, total=2, status=status,
                detail=active.get("last_error") or active.get("error_kind") or active.get("updated_at"),
            )
            events.append(ProgressEvent(
                f"Queue job #{active.get('id')} is {status} for {group_name}",
                level="WARN" if status == "UNCERTAIN" else "INFO",
                source="Smart_Auto_Poster_V2",
            ))

        if unresolved:
            recovery.append(
                f"{unresolved} queue item(s) are UNCERTAIN. Keep generic auto-retry blocked and reconcile delivery evidence first."
            )
        if failed:
            recovery.append(f"{failed} failed/quarantined queue item(s) need review; healthy destinations can continue independently.")
        if total == 0:
            recovery.append("Queue is empty; no posting progress is currently active.")

        return progress_snapshot(
            headline="SMART AUTO POSTER - UNIVERSAL PROGRESS",
            overall=overall,
            group=group,
            task=task,
            events=events,
            metrics=_throughput_metrics(con, counts, columns),
            recovery_messages=recovery,
        )
    finally:
        con.close()
