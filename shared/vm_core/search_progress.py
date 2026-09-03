from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _tables
from .paths import project_root
from .progress import ProgressLine, progress_snapshot

_TERMINAL = {"sent", "failed"}
_ACTIVE = {"pending", "retry"}


def _status_counts(con) -> dict[str, int]:
    rows = con.execute(
        "SELECT lower(status) AS status,COUNT(*) AS n FROM alert_queue GROUP BY lower(status)"
    ).fetchall()
    return {str(row["status"]): int(row["n"] or 0) for row in rows}


def _current_alert(con) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT q.id,q.watch_id,q.chat_id,q.message_id,lower(q.status) AS status,
               q.attempts,q.due_utc,q.last_error,w.name AS watch_name
        FROM alert_queue q
        LEFT JOIN saved_searches w ON w.id=q.watch_id
        WHERE lower(q.status) IN ('pending','retry')
        ORDER BY CASE lower(q.status) WHEN 'retry' THEN 0 ELSE 1 END,q.due_utc,q.id
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def universal_search_progress(root: Path | None = None) -> dict[str, Any]:
    """Return a read-only Universal Search indexing/alert-delivery snapshot."""
    root = root or project_root()
    db_path = root / "bots" / "Universal_Search" / "data" / "universal_search.db"
    con = _connect_readonly(db_path)
    if con is None:
        return progress_snapshot(
            headline="UNIVERSAL SEARCH",
            overall=ProgressLine("Search database unavailable", status="DEGRADED", detail=str(db_path)),
            recovery_messages=["Universal Search database is unavailable; index and alert state were not inferred."],
        )

    try:
        tables = _tables(con)
        metrics: dict[str, Any] = {}
        recovery: list[str] = []

        if "indexed_messages" in tables:
            metrics["indexed_messages"] = int(con.execute("SELECT COUNT(*) FROM indexed_messages").fetchone()[0] or 0)
        else:
            metrics["indexed_messages"] = 0
            recovery.append("Indexed-message table is missing; search index readiness cannot be verified.")

        if "saved_searches" in tables:
            row = con.execute(
                "SELECT COUNT(*) AS total,SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled FROM saved_searches"
            ).fetchone()
            metrics["saved_watches"] = int(row["total"] or 0)
            metrics["enabled_watches"] = int(row["enabled"] or 0)
            metrics["paused_watches"] = metrics["saved_watches"] - metrics["enabled_watches"]

        if "alert_queue" not in tables:
            return progress_snapshot(
                headline="UNIVERSAL SEARCH - UNIVERSAL PROGRESS",
                overall=ProgressLine(
                    "Search index readiness",
                    current=1 if "indexed_messages" in tables else 0,
                    total=1,
                    status="READY" if "indexed_messages" in tables else "DEGRADED",
                    detail=f"indexed_messages={metrics.get('indexed_messages', 0)}",
                ),
                metrics=metrics,
                recovery_messages=recovery + ["Alert queue table is unavailable; passive alert progress was not inferred."],
            )

        counts = _status_counts(con)
        total = sum(counts.values())
        terminal = sum(counts.get(status, 0) for status in _TERMINAL)
        failed = counts.get("failed", 0)
        pending = counts.get("pending", 0)
        retry = counts.get("retry", 0)
        current = _current_alert(con)

        metrics.update(
            {
                "alert_queue_total": total,
                "alert_pending": pending,
                "alert_retry": retry,
                "alert_sent": counts.get("sent", 0),
                "alert_failed": failed,
            }
        )

        if total:
            status = "RUNNING" if pending or retry else "COMPLETE"
            if failed:
                status = "ATTENTION"
            overall = ProgressLine(
                "Passive alert delivery queue",
                current=terminal,
                total=total,
                status=status,
                detail=f"sent={counts.get('sent', 0)} pending={pending} retry={retry} failed={failed}",
            )
        else:
            overall = ProgressLine(
                "Search index ready",
                current=1,
                total=1,
                status="READY",
                detail=f"indexed_messages={metrics.get('indexed_messages', 0)} alert_queue=empty",
            )

        group = None
        task = None
        if current:
            queue_status = str(current.get("status") or "unknown").upper()
            group = ProgressLine(
                str(current.get("watch_name") or f"Watch #{current.get('watch_id')}"),
                current=0,
                total=1,
                status=queue_status,
                detail=f"chat={current.get('chat_id')} due={current.get('due_utc')}",
            )
            task = ProgressLine(
                f"Alert #{current.get('id')}",
                current=0,
                total=1,
                status=queue_status,
                detail=current.get("last_error") or f"attempts={current.get('attempts', 0)} message={current.get('message_id')}",
            )

        if retry:
            recovery.append(f"{retry} alert(s) are waiting for bounded retry backoff; no busy-loop retry is required.")
        if failed:
            recovery.append(f"{failed} alert delivery record(s) are terminally failed and should be reviewed before re-enabling affected watches.")

        return progress_snapshot(
            headline="UNIVERSAL SEARCH - UNIVERSAL PROGRESS",
            overall=overall,
            group=group,
            task=task,
            metrics=metrics,
            recovery_messages=recovery,
        )
    finally:
        con.close()
