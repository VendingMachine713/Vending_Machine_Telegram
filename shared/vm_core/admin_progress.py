from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _tables
from .paths import project_root
from .progress import ProgressLine, progress_snapshot

_SERVICE_NAME = "Admin_Command_Centre"
_RUNTIME_STALE_SECONDS = 300


def _parse_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def admin_command_centre_progress(root: Path | None = None) -> dict[str, Any]:
    """Return read-only Admin Command Centre runtime/control-surface readiness."""
    root = root or project_root()
    db_path = root / "state" / "vm_platform.sqlite3"
    con = _connect_readonly(db_path)
    if con is None:
        return progress_snapshot(
            headline="ADMIN COMMAND CENTRE",
            overall=ProgressLine("Admin runtime evidence unavailable", status="DEGRADED", detail=str(db_path)),
            recovery_messages=["Shared platform database is unavailable; Admin Command Centre runtime state was not inferred."],
        )

    try:
        tables = _tables(con)
        if "services" not in tables:
            return progress_snapshot(
                headline="ADMIN COMMAND CENTRE - UNIVERSAL PROGRESS",
                overall=ProgressLine("Admin runtime evidence unavailable", status="DEGRADED"),
                recovery_messages=["Platform services table is missing; Admin Command Centre readiness cannot be verified."],
            )

        row = con.execute(
            "SELECT runtime_status,pid,last_error,updated_at_utc FROM services WHERE lower(name)=lower(?) LIMIT 1",
            (_SERVICE_NAME,),
        ).fetchone()
        events: list[dict[str, Any]] = []
        if "events" in tables:
            event_rows = con.execute(
                """
                SELECT event_type,severity,payload_json,created_at_utc
                FROM events WHERE lower(source)=lower(?) ORDER BY id DESC LIMIT 8
                """,
                (_SERVICE_NAME,),
            ).fetchall()
            for event in reversed(event_rows):
                message = str(event["event_type"] or "event")
                try:
                    payload = json.loads(event["payload_json"] or "{}")
                    if isinstance(payload, dict) and (payload.get("message") or payload.get("rationale")):
                        message += ": " + str(payload.get("message") or payload.get("rationale"))
                except (TypeError, json.JSONDecodeError):
                    pass
                events.append(
                    {
                        "message": message,
                        "level": str(event["severity"] or "INFO").upper(),
                        "source": _SERVICE_NAME,
                        "at": str(event["created_at_utc"] or ""),
                    }
                )

        if row is None:
            return progress_snapshot(
                headline="ADMIN COMMAND CENTRE - UNIVERSAL PROGRESS",
                overall=ProgressLine("Admin runtime not registered", status="DEGRADED"),
                metrics={"recent_events": len(events)},
                events=events,
                recovery_messages=["Admin Command Centre is not present in shared service runtime evidence."],
            )

        runtime = str(row["runtime_status"] or "UNKNOWN").upper()
        updated = _parse_time(row["updated_at_utc"])
        age = (datetime.now(timezone.utc) - updated).total_seconds() if updated else None
        stale = age is not None and age > _RUNTIME_STALE_SECONDS
        recovery: list[str] = []
        ready = 0
        status = "ATTENTION"
        service_status = runtime

        if runtime == "RUNNING" and not stale:
            ready = 1
            status = "RUNNING"
            service_status = "RUNNING"
        elif stale:
            service_status = "STALE"
            recovery.append(f"Admin Command Centre runtime evidence is stale ({int(age)}s old); verify polling/runtime state.")
        else:
            recovery.append(f"Admin Command Centre is recorded as {runtime}; Telegram administration availability is not confirmed.")
        if row["last_error"]:
            recovery.append(f"Last recorded Admin Command Centre error: {row['last_error']}")

        detail = f"runtime={runtime} pid={row['pid'] or '-'} updated={row['updated_at_utc'] or '-'}"
        return progress_snapshot(
            headline="ADMIN COMMAND CENTRE - UNIVERSAL PROGRESS",
            overall=ProgressLine("Operator control readiness", ready, 1, status, detail),
            task=ProgressLine(
                "Telegram admin control surface",
                ready,
                1,
                "AVAILABLE" if ready else "UNAVAILABLE",
                "Read-only status/progress commands remain separate from guarded mutating commands.",
            ),
            services=[{"name": _SERVICE_NAME, "status": service_status, "detail": detail}],
            metrics={"recent_events": len(events)},
            events=events,
            recovery_messages=recovery,
        )
    finally:
        con.close()
