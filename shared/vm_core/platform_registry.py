from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
from typing import Any

from . import __version__
from .manifests import discover_bots
from .paths import project_root, relative_display
from .service_adapters import adapter_status

REGISTRY_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class ServiceDescriptor:
    name: str
    folder: str
    version: str | None
    classification: str
    entrypoint: str | None
    entrypoint_confidence: str
    launchers: list[str]
    capabilities: list[str]
    runtime_required_env: list[str]
    runtime_optional_env: list[str]
    managed_by_vm: bool
    auto_start: bool
    auto_restart: bool
    databases: list[str]
    tests: list[str]
    manifest_path: str
    adapter_id: str | None
    adapter_status: str
    adapter_confidence: str
    adapter_safe_operations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def describe_services(root: Path | None = None) -> list[ServiceDescriptor]:
    root = root or project_root()
    descriptors: list[ServiceDescriptor] = []
    for bot in discover_bots(root):
        bot_dir = Path(bot.path)
        manifest_path = bot_dir / "BOT_MANIFEST.json"
        manifest = _load_manifest(manifest_path)
        lifecycle = manifest.get("lifecycle") if isinstance(manifest.get("lifecycle"), dict) else {}
        runtime = manifest.get("runtime_requirements") if isinstance(manifest.get("runtime_requirements"), dict) else {}
        adapter = adapter_status(bot)
        descriptors.append(
            ServiceDescriptor(
                name=str(manifest.get("name") or bot.folder),
                folder=bot.folder,
                version=str(manifest.get("version") or bot.version) if (manifest.get("version") or bot.version) is not None else None,
                classification=str(manifest.get("classification") or bot.classification),
                entrypoint=str(manifest.get("entrypoint") or bot.entrypoint) if (manifest.get("entrypoint") or bot.entrypoint) else None,
                entrypoint_confidence=str(manifest.get("entrypoint_confidence") or bot.entrypoint_confidence),
                launchers=_string_list(manifest.get("launchers")) or list(bot.launchers),
                capabilities=sorted(set(_string_list(manifest.get("capabilities")))),
                runtime_required_env=sorted(set(_string_list(runtime.get("env")))),
                runtime_optional_env=sorted(set(_string_list(runtime.get("optional_env")))),
                managed_by_vm=bool(lifecycle.get("managed_by_vm", True)),
                auto_start=bool(lifecycle.get("auto_start", False)),
                auto_restart=bool(lifecycle.get("auto_restart", False)),
                databases=list(bot.databases),
                tests=list(bot.test_files),
                manifest_path=relative_display(manifest_path, root),
                adapter_id=adapter.get("adapter_id"),
                adapter_status=str(adapter.get("status") or "GENERIC_ONLY"),
                adapter_confidence=str(adapter.get("confidence") or "none"),
                adapter_safe_operations=list(adapter.get("safe_operations") or []),
            )
        )
    return sorted(descriptors, key=lambda item: item.name.lower())


def service_registry(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    services = describe_services(root)
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "vm_core_version": __version__,
        "service_count": len(services),
        "managed_count": sum(1 for item in services if item.managed_by_vm),
        "auto_start_count": sum(1 for item in services if item.auto_start),
        "auto_restart_count": sum(1 for item in services if item.auto_restart),
        "adapter_supported_count": sum(1 for item in services if item.adapter_id),
        "adapter_ready_count": sum(1 for item in services if item.adapter_status == "READY"),
        "adapter_evidence_required_count": sum(1 for item in services if item.adapter_status == "EVIDENCE_REQUIRED"),
        "services": [item.to_dict() for item in services],
    }


def write_service_registry(root: Path | None = None) -> Path:
    root = root or project_root()
    path = root / "state" / "platform_service_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(service_registry(root), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def format_service_registry(registry: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        " VM PLATFORM SERVICE REGISTRY",
        "=" * 78,
        f"VM Core:  {registry['vm_core_version']}",
        f"Services: {registry['service_count']} | managed={registry['managed_count']} | auto-start={registry['auto_start_count']} | auto-restart={registry['auto_restart_count']}",
        f"Adapters: supported={registry['adapter_supported_count']} | ready={registry['adapter_ready_count']} | evidence-required={registry['adapter_evidence_required_count']}",
        "",
    ]
    for item in registry["services"]:
        caps = ",".join(item["capabilities"]) if item["capabilities"] else "-"
        required = ",".join(item["runtime_required_env"]) if item["runtime_required_env"] else "-"
        lines.append(
            f"{item['name']:<28} v{item['version'] or 'unknown':<10} managed={str(item['managed_by_vm']).lower():<5} "
            f"entry={item['entrypoint'] or '-'}"
        )
        lines.append(f"  capabilities={caps}")
        lines.append(f"  required_config_keys={required}")
        lines.append(
            f"  adapter={item['adapter_id'] or '-'} status={item['adapter_status']} confidence={item['adapter_confidence']}"
        )
    return "\n".join(lines)
