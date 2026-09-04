from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class RecoveryHistory:
    def __init__(self, root: Path, *, base_cooldown_seconds: int = 120,
                 max_attempts: int = 3, window_seconds: int = 3600):
        self.root = Path(root)
        self.path = self.root / "state" / "recovery_history.json"
        self.base_cooldown_seconds = max(30, int(base_cooldown_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = max(self.base_cooldown_seconds, int(window_seconds))

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"services": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"services": {}}
        except Exception:
            return {"services": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def status(self, service: str, now: datetime | None = None) -> dict[str, Any]:
        now = now or _utcnow()
        row = dict((self.load().get("services") or {}).get(service) or {})
        attempts = int(row.get("attempts") or 0)
        first = _parse(row.get("window_started_at"))
        last = _parse(row.get("last_attempt_at"))
        if first is None or (now - first).total_seconds() > self.window_seconds:
            attempts = 0
            first = None
            last = None
        cooldown = self.base_cooldown_seconds * (2 ** max(0, attempts - 1)) if attempts else 0
        next_allowed = last + timedelta(seconds=cooldown) if last else now
        return {
            "attempts": attempts,
            "limited": attempts >= self.max_attempts,
            "cooling_down": bool(last and now < next_allowed),
            "cooldown_seconds": cooldown,
            "next_allowed_at": next_allowed.isoformat(),
        }

    def record_attempt(self, service: str, *, action: str, success: bool | None = None,
                       now: datetime | None = None) -> None:
        now = now or _utcnow()
        data = self.load()
        services = data.setdefault("services", {})
        current = self.status(service, now)
        row = dict(services.get(service) or {})
        if int(current["attempts"]) == 0:
            row["window_started_at"] = now.isoformat()
        row.update({
            "attempts": int(current["attempts"]) + 1,
            "last_attempt_at": now.isoformat(),
            "last_action": str(action),
            "last_success": success,
        })
        services[service] = row
        self._save(data)

    def reset(self, service: str) -> None:
        data = self.load()
        services = data.setdefault("services", {})
        if service in services:
            services.pop(service, None)
            self._save(data)
