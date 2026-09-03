from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(slots=True)
class ProgressLine:
    label: str
    current: int = 0
    total: int = 0
    status: str = "PENDING"
    detail: str | None = None

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return max(0, min(100, round((self.current / self.total) * 100)))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["percent"] = self.percent
        return data


@dataclass(slots=True)
class ProgressEvent:
    message: str
    level: str = "INFO"
    source: str = "system"
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _normalise_status(value: str | None) -> str:
    value = str(value or "UNKNOWN").upper()
    if value in {"ALIVE", "RUNNING", "ACTIVE", "OK", "HEALTHY"}:
        return "HEALTHY"
    if value in {"WARN", "WARNING", "DEGRADED", "STALE"}:
        return "DEGRADED"
    if value in {"FAIL", "FAILED", "ERROR", "DOWN", "STOPPED"}:
        return "FAILED"
    return value


def render_bar(percent: int, width: int = 24) -> str:
    percent = max(0, min(100, int(percent)))
    filled = round((percent / 100) * width)
    return "[" + ("#" * filled) + ("-" * (width - filled)) + f"] {percent:3d}%"


def progress_snapshot(
    *,
    headline: str,
    overall: ProgressLine,
    group: ProgressLine | None = None,
    task: ProgressLine | None = None,
    services: Iterable[dict[str, Any]] = (),
    events: Iterable[ProgressEvent | dict[str, Any]] = (),
    recovery_messages: Iterable[str] = (),
) -> dict[str, Any]:
    service_rows: list[dict[str, Any]] = []
    for service in services:
        raw = str(service.get("runtime_status") or service.get("status") or "UNKNOWN")
        service_rows.append(
            {
                "name": service.get("name") or service.get("service") or "unknown",
                "status": _normalise_status(raw),
                "raw_status": raw.upper(),
                "detail": service.get("detail") or service.get("message"),
            }
        )

    event_rows: list[dict[str, Any]] = []
    for event in events:
        if isinstance(event, ProgressEvent):
            event_rows.append(event.to_dict())
        else:
            event_rows.append(dict(event))

    return {
        "headline": headline,
        "overall": overall.to_dict(),
        "group": group.to_dict() if group else None,
        "task": task.to_dict() if task else None,
        "services": service_rows,
        "events": event_rows,
        "recovery_messages": list(recovery_messages),
    }


def format_progress(snapshot: dict[str, Any]) -> str:
    lines = ["=" * 78, f" {snapshot['headline']}", "=" * 78]
    for key, title in (("overall", "OVERALL"), ("group", "CURRENT GROUP"), ("task", "CURRENT TASK")):
        row = snapshot.get(key)
        if not row:
            continue
        lines.append(
            f"{title:<14} {render_bar(int(row.get('percent', 0)))}  "
            f"{row.get('label', '')}  [{row.get('status', 'UNKNOWN')}]"
        )
        if row.get("detail"):
            lines.append(f"{'':14} {row['detail']}")

    services = snapshot.get("services") or []
    if services:
        lines.extend(["-" * 78, "HEALTH"])
        for row in services:
            suffix = f" - {row['detail']}" if row.get("detail") else ""
            lines.append(f"{row['status']:<10} {row['name']}{suffix}")

    events = snapshot.get("events") or []
    if events:
        lines.extend(["-" * 78, "LIVE EVENT FEED"])
        for event in events[-8:]:
            lines.append(f"{event.get('level', 'INFO'):<8} {event.get('source', 'system')}: {event.get('message', '')}")

    recovery = snapshot.get("recovery_messages") or []
    if recovery:
        lines.extend(["-" * 78, "RECOVERY / NEXT ACTION"])
        lines.extend(f"- {message}" for message in recovery)
    return "\n".join(lines)
