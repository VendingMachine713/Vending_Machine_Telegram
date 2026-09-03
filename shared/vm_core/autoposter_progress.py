from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _resolve_bot_path, _tables
from .paths import project_root
from .progress import ProgressEvent, ProgressLine, progress_snapshot

_TERMINAL = {"sent", "failed", "cancelled", "quarantined"}
_ACTIVE = {"pending", "retry", "processing", "sending", "uncertain"}


def _count_statuses(con) -> dict[str, int]:
    rows = con.execute("SELECT lower(status) AS status, COUNT(*) AS n FROM queue GROUP BY lower(status)").fetchall()
    return {str(row["status"]): int(row["n"] or 0) for row in rows}


def _latest_active(con) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT q.id,q.campaign_id,q.group_id,q.account_key,lower(q.status) AS status,
               q.error_kind,q.last_error,q.updated_at,d.group_name
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

        counts = _count_statuses(con)
        total = sum(counts.values())
        complete = sum(counts.get(state, 0) for state in _TERMINAL)
        unresolved = counts.get("uncertain", 0)
        failed = counts.get("failed", 0) + counts.get("quarantined", 0)
        active = _latest_active(con)

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
        events: list[ProgressEvent] = []
        recovery: list[str] = []

        if active:
            group_name = active.get("group_name") or str(active.get("group_id") or "unknown destination")
            status = str(active.get("status") or "unknown").upper()
            group = ProgressLine(
                str(group_name), current=0 if status in {"PENDING", "RETRY"} else 1,
                total=1, status=status,
                detail=f"campaign={active.get('campaign_id')} account={active.get('account_key') or 'unassigned'}",
            )
            task = ProgressLine(
                f"Queue job #{active.get('id')}", current=0 if status in {"PENDING", "RETRY"} else 1,
                total=1, status=status,
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
            recovery_messages=recovery,
        )
    finally:
        con.close()
