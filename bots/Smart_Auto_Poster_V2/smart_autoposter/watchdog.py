from __future__ import annotations

import json
import socket
from datetime import datetime, timezone

from .db import Database, utcnow
from .notifications import NotificationManager


def _dt(value: str | None):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def network_available(host: str, port: int, timeout: float = 4.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


class Watchdog:
    def __init__(self, db: Database, *, stale_seconds: int = 180, notifier: NotificationManager | None = None):
        self.db = db
        self.stale_seconds = max(30, int(stale_seconds))
        self.notifier = notifier or NotificationManager(db)

    def beat(self, component: str, status: str = "ok", details=None):
        payload = json.dumps(details, ensure_ascii=False, default=str) if isinstance(details, (dict, list)) else (str(details) if details is not None else None)
        return self.db.heartbeat(component, status, payload)

    def snapshot(self) -> dict:
        now = datetime.now(timezone.utc)
        with self.db.connect() as con:
            rows = con.execute("SELECT * FROM heartbeats ORDER BY component").fetchall()
        out = {}
        for r in rows:
            dt = _dt(r["last_seen_at"])
            age = (now - dt).total_seconds() if dt else None
            out[r["component"]] = {
                "last_seen_at": r["last_seen_at"], "status": r["status"], "details": r["details"],
                "age_seconds": round(age, 1) if age is not None else None,
                "stale": bool(age is not None and age > self.stale_seconds),
            }
        return out

    def evaluate(self, required: tuple[str, ...] = ("service", "scheduler", "worker")) -> list[str]:
        snap = self.snapshot()
        problems = []
        for component in required:
            state = snap.get(component)
            if not state:
                problems.append(f"{component}: no heartbeat")
            elif state["stale"]:
                problems.append(f"{component}: stale heartbeat ({state['age_seconds']}s)")
            elif state["status"] not in {"ok", "idle", "paused"}:
                problems.append(f"{component}: status={state['status']}")
        if problems:
            key = "watchdog:" + "|".join(sorted(problems))
            self.notifier.emit("IMPORTANT", "Smart Auto Poster watchdog", "\n".join(problems), dedupe_key=key, event_type="watchdog_problem", dedupe_window_seconds=3600)
        return problems
