from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .manifests import BotInfo, discover_bots
from .paths import project_root

ADAPTER_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class ServiceAdapter:
    service: str
    adapter_id: str
    confidence: str
    preferred_entrypoint: str | None
    preferred_launcher: str | None
    read_surfaces: tuple[str, ...]
    capabilities: tuple[str, ...]
    safe_operations: tuple[str, ...] = ("status", "health", "inspect")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("read_surfaces", "capabilities", "safe_operations"):
            data[key] = list(data[key])
        data["contract_version"] = ADAPTER_CONTRACT_VERSION
        return data


_BUILTIN_ADAPTERS: dict[str, ServiceAdapter] = {
    "universal_search": ServiceAdapter(
        service="Universal_Search",
        adapter_id="universal-search-v1",
        confidence="high",
        preferred_entrypoint="main.py",
        preferred_launcher="START.ps1",
        read_surfaces=("data/universal_search.db",),
        capabilities=("search", "index", "watch", "alerts"),
    ),
    "vm_guard": ServiceAdapter(
        service="VM_Guard",
        adapter_id="vm-guard-v1",
        confidence="high",
        preferred_entrypoint="main.py",
        preferred_launcher="START.ps1",
        read_surfaces=(),
        capabilities=("guard", "risk", "health"),
    ),
    "admin_command_centre": ServiceAdapter(
        service="Admin_Command_Centre",
        adapter_id="admin-command-centre-v1",
        confidence="high",
        preferred_entrypoint="main.py",
        preferred_launcher="START_ADMIN_COMMAND_CENTRE.bat",
        read_surfaces=(),
        capabilities=("platform_status", "platform_health", "service_lifecycle"),
    ),
    "vm_relationship_manager": ServiceAdapter(
        service="VM_Relationship_Manager",
        adapter_id="relationship-manager-v1",
        confidence="high",
        preferred_entrypoint="main.py",
        preferred_launcher="START_VM_RELATIONSHIPS.ps1",
        read_surfaces=(),
        capabilities=("relationships", "contacts", "passive_monitoring"),
    ),
    "smart_auto_poster_v2": ServiceAdapter(
        service="Smart_Auto_Poster_V2",
        adapter_id="smart-auto-poster-v1",
        confidence="high",
        preferred_entrypoint="app.py",
        preferred_launcher="RUN_SERVICE.ps1",
        read_surfaces=("data/smart_autoposter.sqlite3",),
        capabilities=("posting", "destinations", "delivery_intelligence", "recovery"),
    ),
}


def adapter_for(service: str) -> ServiceAdapter | None:
    return _BUILTIN_ADAPTERS.get(str(service).strip().lower())


def _path_exists(bot_dir: Path, relative: str | None) -> bool:
    if not relative:
        return True
    return (bot_dir / Path(relative)).is_file()


def adapter_status(bot: BotInfo) -> dict[str, Any]:
    """Validate one adapter against repository evidence without executing the service."""
    adapter = adapter_for(bot.folder)
    if adapter is None:
        return {
            "contract_version": ADAPTER_CONTRACT_VERSION,
            "service": bot.folder,
            "supported": False,
            "status": "GENERIC_ONLY",
            "adapter_id": None,
            "confidence": "none",
            "evidence": [],
            "missing": [],
            "safe_operations": ["status", "health", "inspect"],
        }

    bot_dir = Path(bot.path)
    evidence: list[str] = []
    missing: list[str] = []

    if adapter.preferred_entrypoint and _path_exists(bot_dir, adapter.preferred_entrypoint):
        evidence.append(f"entrypoint:{adapter.preferred_entrypoint}")
    elif adapter.preferred_entrypoint:
        missing.append(f"entrypoint:{adapter.preferred_entrypoint}")

    if adapter.preferred_launcher and _path_exists(bot_dir, adapter.preferred_launcher):
        evidence.append(f"launcher:{adapter.preferred_launcher}")
    elif adapter.preferred_launcher:
        missing.append(f"launcher:{adapter.preferred_launcher}")

    for surface in adapter.read_surfaces:
        if _path_exists(bot_dir, surface):
            evidence.append(f"read_surface:{surface}")
        else:
            # Runtime data can legitimately be absent in fresh/test checkouts, so this
            # remains evidence debt rather than making the adapter unusable.
            missing.append(f"read_surface:{surface}")

    runnable_missing = any(item.startswith(("entrypoint:", "launcher:")) for item in missing)
    return {
        **adapter.to_dict(),
        "supported": True,
        "status": "EVIDENCE_REQUIRED" if runnable_missing else "READY",
        "evidence": evidence,
        "missing": missing,
    }


def adapter_registry(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    rows = [adapter_status(bot) for bot in discover_bots(root)]
    return {
        "contract_version": ADAPTER_CONTRACT_VERSION,
        "service_count": len(rows),
        "supported_count": sum(1 for row in rows if row["supported"]),
        "ready_count": sum(1 for row in rows if row["status"] == "READY"),
        "generic_only_count": sum(1 for row in rows if row["status"] == "GENERIC_ONLY"),
        "evidence_required_count": sum(1 for row in rows if row["status"] == "EVIDENCE_REQUIRED"),
        "services": rows,
        "automatic_execution": False,
        "external_action_authority": False,
    }
