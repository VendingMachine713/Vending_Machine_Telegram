from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any

from . import __version__
from .paths import project_root
from .platform_registry import describe_services
from .services import service_status

RUNTIME_REGISTRY_SCHEMA_VERSION = 1


def runtime_registry(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    descriptors = {item.name: item for item in describe_services(root)}
    status_rows = {str(row["name"]): row for row in service_status(root)}

    services: list[dict[str, Any]] = []
    for name in sorted(descriptors, key=str.lower):
        descriptor = descriptors[name]
        row = status_rows.get(name, {})
        services.append({
            "service": name,
            "version": descriptor.version,
            "classification": descriptor.classification,
            "managed_by_vm": descriptor.managed_by_vm,
            "runtime_status": str(row.get("runtime_status") or "UNKNOWN"),
            "process_alive": bool(row.get("process_alive", False)),
            "pid": int(row["pid"]) if row.get("pid") is not None else None,
            "entrypoint": descriptor.entrypoint,
            "launcher": descriptor.launchers[0] if descriptor.launchers else None,
        })

    return {
        "schema_version": RUNTIME_REGISTRY_SCHEMA_VERSION,
        "vm_core_version": __version__,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "service_count": len(services),
        "running_count": sum(1 for item in services if item["process_alive"]),
        "services": services,
    }


def write_runtime_registry(root: Path | None = None) -> Path:
    root = root or project_root()
    path = root / "state" / "runtime_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(runtime_registry(root), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def format_runtime_registry(registry: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        " VM PLATFORM RUNTIME REGISTRY",
        "=" * 78,
        f"VM Core: {registry['vm_core_version']}",
        f"Services: {registry['service_count']} | running={registry['running_count']}",
        "",
    ]
    for item in registry["services"]:
        state = "ALIVE" if item["process_alive"] else item["runtime_status"]
        lines.append(
            f"{item['service']:<28} {state:<10} pid={item['pid'] if item['pid'] is not None else '-':<8} "
            f"version={item['version'] or 'unknown'}"
        )
    return "\n".join(lines)
