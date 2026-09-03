from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from . import __version__
from .paths import project_root
from .platform_registry import describe_services

CONFIG_REGISTRY_SCHEMA_VERSION = 1


def configuration_registry(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    services = []
    required_total = 0
    optional_total = 0
    for item in describe_services(root):
        required = list(item.runtime_required_env)
        optional = list(item.runtime_optional_env)
        required_total += len(required)
        optional_total += len(optional)
        services.append({
            "service": item.name,
            "required_keys": required,
            "optional_keys": optional,
        })
    return {
        "schema_version": CONFIG_REGISTRY_SCHEMA_VERSION,
        "vm_core_version": __version__,
        "service_count": len(services),
        "required_key_count": required_total,
        "optional_key_count": optional_total,
        "services": services,
    }


def write_configuration_registry(root: Path | None = None) -> Path:
    root = root or project_root()
    path = root / "state" / "config_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(configuration_registry(root), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def format_configuration_registry(registry: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        " VM PLATFORM CONFIGURATION REGISTRY",
        "=" * 78,
        f"VM Core: {registry['vm_core_version']}",
        f"Services: {registry['service_count']} | required keys={registry['required_key_count']} | optional keys={registry['optional_key_count']}",
        "",
    ]
    for item in registry["services"]:
        required = ",".join(item["required_keys"]) if item["required_keys"] else "-"
        optional = ",".join(item["optional_keys"]) if item["optional_keys"] else "-"
        lines.append(f"{item['service']}")
        lines.append(f"  required={required}")
        lines.append(f"  optional={optional}")
    return "\n".join(lines)
