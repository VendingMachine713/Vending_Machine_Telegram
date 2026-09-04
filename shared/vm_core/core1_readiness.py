from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__
from .config_registry import configuration_registry
from .foundation import foundation_report
from .paths import project_root
from .platform_registry import service_registry
from .runtime_registry import runtime_registry

READINESS_SCHEMA_VERSION = 1


def _integration_signals(bot_dir: Path) -> dict[str, bool]:
    source = ""
    for path in bot_dir.rglob("*.py"):
        if any(part in {".venv", "__pycache__", "archive", "backups"} for part in path.parts):
            continue
        try:
            source += "\n" + path.read_text(encoding="utf-8", errors="ignore")[:200000]
        except OSError:
            continue
    return {
        "service_context": "shared.vm_core.service_context" in source,
        "event_publisher": "shared.vm_core.publisher" in source or "BotEventPublisher" in source,
        "shared_logging": "shared.vm_core.logging_setup" in source,
    }


def core1_readiness(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    foundation = foundation_report(root)
    services = service_registry(root)
    config = configuration_registry(root)
    runtime = runtime_registry(root)

    expected = services["service_count"]
    checks = [
        {
            "name": "foundation_contract",
            "status": "PASS" if foundation["status"] == "PASS" else "FAIL",
            "detail": f"errors={foundation['summary']['ERROR']} warnings={foundation['summary']['WARN']}",
        },
        {
            "name": "service_registry",
            "status": "PASS" if expected > 0 else "FAIL",
            "detail": f"services={expected}",
        },
        {
            "name": "configuration_registry",
            "status": "PASS" if config["service_count"] == expected else "FAIL",
            "detail": f"services={config['service_count']}",
        },
        {
            "name": "runtime_registry",
            "status": "PASS" if runtime["service_count"] == expected else "FAIL",
            "detail": f"services={runtime['service_count']} running={runtime['running_count']}",
        },
    ]

    adoption = []
    for item in services["services"]:
        bot_dir = root / "bots" / item["folder"]
        signals = _integration_signals(bot_dir)
        adoption.append({
            "service": item["name"],
            **signals,
            "adopted_count": sum(1 for value in signals.values() if value),
            "available_count": len(signals),
        })

    failures = sum(1 for check in checks if check["status"] == "FAIL")
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "vm_core_version": __version__,
        "status": "PASS" if failures == 0 else "FAIL",
        "checks": checks,
        "service_count": expected,
        "integration_adoption": adoption,
        "note": "Integration adoption is informational and does not block Core 1 infrastructure readiness.",
    }


def format_core1_readiness(report: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        " VM CORE 1 FOUNDATION READINESS",
        "=" * 78,
        f"VM Core: {report['vm_core_version']}",
        f"Status:  {report['status']}",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"[{check['status']:<4}] {check['name']}: {check['detail']}")
    lines += ["", "Incremental bot adoption:"]
    for item in report["integration_adoption"]:
        lines.append(
            f"  {item['service']:<28} {item['adopted_count']}/{item['available_count']} "
            f"context={item['service_context']} events={item['event_publisher']} logging={item['shared_logging']}"
        )
    lines += ["", report["note"]]
    return "\n".join(lines)
