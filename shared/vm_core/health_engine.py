from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifests import discover_bots
from .paths import project_root
from .runtime_requirements import runtime_configuration_status
from .services import service_status
from .sqlite_helpers import integrity_check

HEALTH_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HealthSignal:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _overall(signals: list[HealthSignal]) -> str:
    statuses = {signal.status for signal in signals}
    if "OFFLINE" in statuses:
        return "OFFLINE"
    if "ATTENTION_REQUIRED" in statuses:
        return "ATTENTION_REQUIRED"
    if "DEGRADED" in statuses:
        return "DEGRADED"
    if "RECOVERING" in statuses:
        return "RECOVERING"
    return "HEALTHY"


def _db_signals(bot) -> list[HealthSignal]:
    signals: list[HealthSignal] = []
    for rel in bot.databases[:20]:
        path = Path(bot.path) / rel
        try:
            result = integrity_check(path)
        except FileNotFoundError:
            signals.append(HealthSignal("database", "DEGRADED", f"missing: {rel}"))
        except Exception as exc:
            signals.append(HealthSignal("database", "ATTENTION_REQUIRED", f"{rel}: {type(exc).__name__}: {exc}"))
        else:
            status = "HEALTHY" if result == "ok" else "ATTENTION_REQUIRED"
            signals.append(HealthSignal("database", status, f"{rel}: {result}"))
    return signals


def health_snapshot(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    runtime = {row["name"]: row for row in service_status(root)}
    services: list[dict[str, Any]] = []

    for bot in discover_bots(root):
        row = runtime.get(bot.folder, {})
        cfg = runtime_configuration_status(Path(bot.path))
        signals: list[HealthSignal] = []

        if bot.classification == "PLACEHOLDER":
            signals.append(HealthSignal("classification", "DEGRADED", "planned/placeholder service"))
        else:
            signals.append(HealthSignal("classification", "HEALTHY", "canonical service"))

        if not cfg["configured"]:
            signals.append(HealthSignal("configuration", "ATTENTION_REQUIRED", "required configuration missing"))
        else:
            signals.append(HealthSignal("configuration", "HEALTHY", "required configuration present"))

        process_alive = bool(row.get("process_alive", False))
        runtime_status = str(row.get("runtime_status") or "UNKNOWN")
        if process_alive:
            signals.append(HealthSignal("process", "HEALTHY", f"alive pid={row.get('pid')}"))
        elif runtime_status == "RECOVERING":
            signals.append(HealthSignal("process", "RECOVERING", "recovery in progress"))
        elif runtime_status in {"STOPPED", "UNKNOWN"}:
            signals.append(HealthSignal("process", "DEGRADED", f"not running ({runtime_status})"))
        else:
            signals.append(HealthSignal("process", "ATTENTION_REQUIRED", f"runtime status={runtime_status}"))

        if not bot.entrypoint and not bot.launchers:
            signals.append(HealthSignal("runnable", "ATTENTION_REQUIRED", "no entrypoint or launcher"))
        else:
            signals.append(HealthSignal("runnable", "HEALTHY", "runnable target detected"))

        signals.extend(_db_signals(bot))
        services.append({
            "service": bot.folder,
            "status": _overall(signals),
            "runtime_status": runtime_status,
            "process_alive": process_alive,
            "signals": [signal.to_dict() for signal in signals],
        })

    counts = {
        status: sum(1 for item in services if item["status"] == status)
        for status in ("HEALTHY", "DEGRADED", "RECOVERING", "ATTENTION_REQUIRED", "OFFLINE")
    }
    platform_status = "ATTENTION_REQUIRED" if counts["ATTENTION_REQUIRED"] else (
        "DEGRADED" if counts["DEGRADED"] else (
            "RECOVERING" if counts["RECOVERING"] else "HEALTHY"
        )
    )
    return {
        "schema_version": HEALTH_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": platform_status,
        "service_count": len(services),
        "summary": counts,
        "services": services,
    }


def format_health_snapshot(snapshot: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        " VM CORE UNIVERSAL HEALTH",
        "=" * 78,
        f"Status: {snapshot['status']}",
        f"Services: {snapshot['service_count']}",
        "",
    ]
    for item in snapshot["services"]:
        lines.append(f"{item['service']:<28} {item['status']}")
        for signal in item["signals"]:
            lines.append(f"  - {signal['name']}: {signal['status']} | {signal['detail']}")
    lines += [
        "",
        "Summary: " + " ".join(f"{key}={value}" for key, value in snapshot["summary"].items()),
    ]
    return "\n".join(lines)
