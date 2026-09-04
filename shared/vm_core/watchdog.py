from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .heartbeat import heartbeat_snapshot
from .health_engine import health_snapshot
from .manifests import discover_bots
from .paths import project_root
from .services import service_status

WATCHDOG_SCHEMA_VERSION = 1


def watchdog_snapshot(root: Path | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    root = root or project_root()
    now = now or datetime.now(timezone.utc)
    health = health_snapshot(root)
    heartbeats = heartbeat_snapshot(root, now=now)
    heartbeat_by_service = {item["service"]: item for item in heartbeats["heartbeats"]}
    runtime = {row["name"]: row for row in service_status(root)}
    health_by_service = {row["service"]: row for row in health["services"]}

    services: list[dict[str, Any]] = []
    for bot in discover_bots(root):
        hb = heartbeat_by_service.get(bot.folder)
        rt = runtime.get(bot.folder, {})
        hs = health_by_service.get(bot.folder, {})
        process_alive = bool(rt.get("process_alive"))
        findings: list[dict[str, str]] = []

        if process_alive and hb is None:
            findings.append({
                "code": "HEARTBEAT_MISSING",
                "severity": "WARNING",
                "detail": "process is alive but no universal heartbeat has been recorded",
            })
        elif hb is not None and hb["freshness"] == "STALE":
            findings.append({
                "code": "HEARTBEAT_STALE",
                "severity": "WARNING",
                "detail": f"heartbeat age {hb['age_seconds']:.1f}s",
            })
        elif hb is not None and hb["freshness"] == "EXPIRED":
            findings.append({
                "code": "HEARTBEAT_EXPIRED",
                "severity": "ERROR",
                "detail": f"heartbeat age {hb['age_seconds']:.1f}s",
            })

        if not process_alive and hb is not None and hb["freshness"] == "FRESH":
            findings.append({
                "code": "PROCESS_HEARTBEAT_DISAGREEMENT",
                "severity": "ERROR",
                "detail": "fresh heartbeat exists while tracked process is not alive",
            })

        health_status = str(hs.get("status") or "UNKNOWN")
        if health_status == "ATTENTION_REQUIRED":
            findings.append({
                "code": "HEALTH_ATTENTION_REQUIRED",
                "severity": "ERROR",
                "detail": "universal health engine requires attention",
            })

        state = "HEALTHY"
        if any(item["severity"] == "ERROR" for item in findings):
            state = "ATTENTION_REQUIRED"
        elif findings:
            state = "DEGRADED"

        services.append({
            "service": bot.folder,
            "state": state,
            "process_alive": process_alive,
            "heartbeat": hb,
            "health_status": health_status,
            "findings": findings,
        })

    summary = {
        key: sum(1 for item in services if item["state"] == key)
        for key in ("HEALTHY", "DEGRADED", "ATTENTION_REQUIRED")
    }
    platform_state = "ATTENTION_REQUIRED" if summary["ATTENTION_REQUIRED"] else (
        "DEGRADED" if summary["DEGRADED"] else "HEALTHY"
    )
    return {
        "schema_version": WATCHDOG_SCHEMA_VERSION,
        "generated_at_utc": now.astimezone(timezone.utc).isoformat(),
        "state": platform_state,
        "service_count": len(services),
        "summary": summary,
        "services": services,
    }


def format_watchdog_snapshot(snapshot: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        " VM CORE UNIVERSAL WATCHDOG",
        "=" * 78,
        f"State: {snapshot['state']}",
        "",
    ]
    for item in snapshot["services"]:
        lines.append(f"{item['service']:<28} {item['state']}")
        for finding in item["findings"]:
            lines.append(f"  - {finding['severity']}: {finding['code']} | {finding['detail']}")
    lines += [
        "",
        "Summary: " + " ".join(f"{k}={v}" for k, v in snapshot["summary"].items()),
    ]
    return "\n".join(lines)
