from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any

from .db import PlatformDB
from .paths import project_root

HEARTBEAT_SCHEMA_VERSION = 1
DEFAULT_FRESH_SECONDS = 60
DEFAULT_STALE_SECONDS = 180


@dataclass(frozen=True)
class HeartbeatState:
    service: str
    instance_id: str
    status: str
    observed_at_utc: str
    age_seconds: float
    freshness: str
    active_task: str | None
    counters: dict[str, Any]
    last_success_utc: str | None
    last_error: str | None
    recovery_state: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def freshness_for_age(age_seconds: float, *, fresh_seconds: int = DEFAULT_FRESH_SECONDS,
                      stale_seconds: int = DEFAULT_STALE_SECONDS) -> str:
    if age_seconds <= fresh_seconds:
        return "FRESH"
    if age_seconds <= stale_seconds:
        return "STALE"
    return "EXPIRED"


def record_heartbeat(service: str, instance_id: str, *, status: str = "healthy",
                     active_task: str | None = None, counters: dict[str, Any] | None = None,
                     last_success_utc: str | None = None, last_error: str | None = None,
                     recovery_state: str | None = None, observed_at_utc: str | None = None,
                     root: Path | None = None) -> None:
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    db.record_heartbeat(
        service,
        instance_id,
        status,
        active_task=active_task,
        counters=counters,
        last_success_utc=last_success_utc,
        last_error=last_error,
        recovery_state=recovery_state,
        observed_at_utc=observed_at_utc,
    )


def heartbeat_snapshot(root: Path | None = None, *, now: datetime | None = None,
                       fresh_seconds: int = DEFAULT_FRESH_SECONDS,
                       stale_seconds: int = DEFAULT_STALE_SECONDS) -> dict[str, Any]:
    root = root or project_root()
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    db = PlatformDB(root=root)
    db.init()
    items: list[dict[str, Any]] = []
    for row in db.latest_heartbeats():
        observed = _parse_utc(str(row["observed_at_utc"]))
        age = max(0.0, (now - observed).total_seconds())
        try:
            counters = json.loads(row.get("counters_json") or "{}")
        except json.JSONDecodeError:
            counters = {}
        state = HeartbeatState(
            service=str(row["service"]),
            instance_id=str(row["instance_id"]),
            status=str(row["status"]),
            observed_at_utc=observed.isoformat(),
            age_seconds=round(age, 3),
            freshness=freshness_for_age(age, fresh_seconds=fresh_seconds, stale_seconds=stale_seconds),
            active_task=row.get("active_task"),
            counters=counters if isinstance(counters, dict) else {},
            last_success_utc=row.get("last_success_utc"),
            last_error=row.get("last_error"),
            recovery_state=row.get("recovery_state"),
        )
        items.append(state.to_dict())

    summary = {
        key: sum(1 for item in items if item["freshness"] == key)
        for key in ("FRESH", "STALE", "EXPIRED")
    }
    return {
        "schema_version": HEARTBEAT_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "fresh_seconds": fresh_seconds,
        "stale_seconds": stale_seconds,
        "heartbeat_count": len(items),
        "summary": summary,
        "heartbeats": items,
    }


def format_heartbeat_snapshot(snapshot: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        " VM CORE HEARTBEATS",
        "=" * 78,
        f"Heartbeats: {snapshot['heartbeat_count']} | fresh={snapshot['summary']['FRESH']} "
        f"stale={snapshot['summary']['STALE']} expired={snapshot['summary']['EXPIRED']}",
        "",
    ]
    for item in snapshot["heartbeats"]:
        lines.append(
            f"{item['service']:<28} {item['freshness']:<8} age={item['age_seconds']:>7.1f}s "
            f"state={item['status']} task={item['active_task'] or '-'}"
        )
    return "\n".join(lines)
