from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _tables
from .paths import project_root
from .progress import ProgressLine, progress_snapshot

_SERVICE_NAME = "VM_Guard"
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


def _load_config(bot_dir: Path) -> dict[str, Any]:
    path = bot_dir / "state" / "config.json"
    defaults = {"mutations_enabled": False, "risk_threshold": 60, "flood_delete": False}
    if not path.is_file():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    return {**defaults, **data}


def _runtime_state(root: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    db_path = root / "state" / "vm_platform.sqlite3"
    con = _connect_readonly(db_path)
    if con is None:
        return None, []
    try:
        tables = _tables(con)
        service = None
        if "services" in tables:
            row = con.execute(
                "SELECT name,runtime_status,pid,last_error,updated_at_utc FROM services WHERE lower(name)=lower(?) LIMIT 1",
                (_SERVICE_NAME,),
            ).fetchone()
            service = dict(row) if row else None
        events: list[dict[str, Any]] = []
        if "events" in tables:
            rows = con.execute(
                """
                SELECT event_type,severity,payload_json,created_at_utc
                FROM events WHERE lower(source)=lower(?)
                ORDER BY id DESC LIMIT 8
                """,
                (_SERVICE_NAME,),
            ).fetchall()
            for row in reversed(rows):
                message = str(row["event_type"] or "event")
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                    if isinstance(payload, dict):
                        rationale = payload.get("rationale") or payload.get("message")
                        if rationale:
                            message = f"{message}: {rationale}"
                except (TypeError, json.JSONDecodeError):
                    pass
                events.append(
                    {
                        "message": message,
                        "level": str(row["severity"] or "INFO").upper(),
                        "source": _SERVICE_NAME,
                        "at": str(row["created_at_utc"] or ""),
                    }
                )
        return service, events
    finally:
        con.close()


def vm_guard_progress(root: Path | None = None) -> dict[str, Any]:
    """Return a read-only VM Guard progress/readiness snapshot.

    VM Guard is a continuous service rather than a finite campaign, so its
    progress bar represents operational readiness while metrics show the current
    monitor/active mode. No Guard or platform state is modified.
    """
    root = root or project_root()
    bot_dir = root / "bots" / _SERVICE_NAME
    config = _load_config(bot_dir)
    service, events = _runtime_state(root)

    mode = "ACTIVE MODERATION" if bool(config.get("mutations_enabled")) else "MONITOR ONLY"
    recovery: list[str] = []
    services: list[dict[str, Any]] = []
    ready = 0
    overall_status = "DEGRADED"
    runtime_label = "UNKNOWN"

    if service is None:
        recovery.append("VM Guard runtime evidence is unavailable; service state was not inferred.")
        services.append({"name": "VM_Guard", "status": "UNKNOWN", "detail": "no shared runtime evidence"})
    else:
        runtime_label = str(service.get("runtime_status") or "UNKNOWN").upper()
        updated = _parse_time(service.get("updated_at_utc"))
        age = (datetime.now(timezone.utc) - updated).total_seconds() if updated else None
        stale = age is not None and age > _RUNTIME_STALE_SECONDS
        if runtime_label == "RUNNING" and not stale:
            ready = 1
            overall_status = "RUNNING"
            health = "RUNNING"
        elif stale:
            overall_status = "ATTENTION"
            health = "STALE"
            recovery.append(f"VM Guard runtime evidence is stale ({int(age)}s old); verify the service before relying on protection status.")
        else:
            overall_status = "ATTENTION"
            health = runtime_label
            recovery.append(f"VM Guard is recorded as {runtime_label}; continuous monitoring is not confirmed active.")
        detail = f"pid={service.get('pid') or '-'} updated={service.get('updated_at_utc') or '-'}"
        if service.get("last_error"):
            detail += f" error={service['last_error']}"
        services.append({"name": "VM_Guard", "status": health, "detail": detail})

    overall = ProgressLine(
        "Protection readiness",
        current=ready,
        total=1,
        status=overall_status,
        detail=f"mode={mode} risk_threshold={config.get('risk_threshold', 60)} runtime={runtime_label}",
    )
    task = ProgressLine(
        "Continuous risk monitoring",
        current=ready,
        total=1,
        status="MONITORING" if ready else "WAITING",
        detail="Passive detection remains enabled in monitor-only mode; moderation mutations require explicit local enablement.",
    )

    return progress_snapshot(
        headline="VM GUARD - UNIVERSAL PROGRESS",
        overall=overall,
        task=task,
        services=services,
        metrics={
            "mode": mode,
            "risk_threshold": int(config.get("risk_threshold", 60)),
            "flood_delete": bool(config.get("flood_delete", False)),
            "recent_events": len(events),
        },
        events=events,
        recovery_messages=recovery,
    )
