"""Read-only Smart Auto Poster recovery gate.

This adapter is intentionally advisory: it never mutates queue/ledger state and
never authorizes a retry. It reconciles the current delivery evidence with the
platform recovery classifier's review boundary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _resolve_bot_path, _tables
from .paths import project_root


def recovery_preview(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    bot_dir = root / "bots" / "Smart_Auto_Poster_V2"
    db_path = _resolve_bot_path(bot_dir, "DATABASE_PATH", bot_dir / "data" / "smart_autoposter.sqlite3")
    con = _connect_readonly(db_path)
    base = {"mode": "READ_ONLY", "database": str(db_path), "mutations_performed": False, "safe_to_restart": False}
    if con is None:
        return {**base, "status": "BLOCKED", "reason": "database_unavailable", "items": []}
    try:
        tables = _tables(con)
        if "queue" not in tables:
            return {**base, "status": "BLOCKED", "reason": "queue_schema_unavailable", "items": []}
        items: list[dict[str, Any]] = []
        uncertain = con.execute("SELECT id,job_key,status,error_kind FROM queue WHERE status='uncertain' ORDER BY id LIMIT 100").fetchall()
        for row in uncertain:
            items.append({"job_id": row["id"], "job_key": row["job_key"], "classification": "MANUAL_REVIEW", "reason": row["error_kind"] or "uncertain_delivery"})
        open_attempts = 0
        if "delivery_attempts" in tables:
            open_attempts = int(con.execute("SELECT COUNT(*) FROM delivery_attempts WHERE outcome IN ('started','acknowledged')").fetchone()[0])
        if open_attempts:
            items.append({"classification": "MANUAL_REVIEW", "reason": "open_delivery_attempts", "count": open_attempts})
        status = "READY_FOR_REVIEW" if not items else "BLOCKED"
        return {**base, "status": status, "safe_to_restart": False, "uncertain_jobs": len(uncertain), "open_delivery_attempts": open_attempts, "items": items}
    finally:
        con.close()


def format_recovery_preview(report: dict[str, Any]) -> str:
    lines = ["SMART AUTO POSTER RECOVERY PREVIEW", f"Mode: {report.get('mode')}", f"Status: {report.get('status')}", f"Safe to restart automatically: {'yes' if report.get('safe_to_restart') else 'no'}"]
    if report.get("reason"): lines.append(f"Reason: {report['reason']}")
    for item in report.get("items", []): lines.append(f"- {item.get('classification')}: {item.get('reason')}" + (f" ({item.get('count')})" if item.get('count') is not None else ""))
    lines.append("Read-only: no queue rows changed and no Telegram action performed.")
    return "\n".join(lines)
