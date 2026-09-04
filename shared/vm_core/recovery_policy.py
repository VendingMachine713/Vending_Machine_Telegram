from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import project_root

DEFAULT_RECOVERY_POLICY: dict[str, Any] = {
    "enabled": False,
    "apply_safe": False,
    "max_actions_per_pass": 1,
    "services": {},
    "blocked_failure_classes": [
        "AUTHENTICATION",
        "CREDENTIALS",
        "TELEGRAM_LIMIT",
        "SESSION",
        "DELIVERY_AMBIGUITY",
        "DATABASE_CORRUPTION",
    ],
}


def policy_path(root: Path | None = None) -> Path:
    root = root or project_root()
    return root / "config" / "vm_recovery_policy.json"


def load_recovery_policy(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    result = json.loads(json.dumps(DEFAULT_RECOVERY_POLICY))
    path = policy_path(root)
    if not path.is_file():
        return result
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        result["invalid"] = True
        return result
    if not isinstance(raw, dict):
        result["invalid"] = True
        return result
    for key in ("enabled", "apply_safe", "max_actions_per_pass", "blocked_failure_classes"):
        if key in raw:
            result[key] = raw[key]
    if isinstance(raw.get("services"), dict):
        result["services"] = raw["services"]
    result["enabled"] = bool(result.get("enabled", False))
    result["apply_safe"] = bool(result.get("apply_safe", False))
    result["max_actions_per_pass"] = max(0, min(3, int(result.get("max_actions_per_pass", 1))))
    if not isinstance(result.get("blocked_failure_classes"), list):
        result["blocked_failure_classes"] = list(DEFAULT_RECOVERY_POLICY["blocked_failure_classes"])
    return result


def service_recovery_policy(service: str, manifest_lifecycle: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    central = load_recovery_policy(root)
    override = (central.get("services") or {}).get(service) or {}
    if not isinstance(override, dict):
        override = {}
    managed = bool(manifest_lifecycle.get("managed_by_vm", False))
    return {
        "managed_by_vm": managed,
        "auto_start": bool(manifest_lifecycle.get("auto_start", False) or (managed and override.get("auto_start", False))),
        "auto_restart": bool(manifest_lifecycle.get("auto_restart", False) or (managed and override.get("auto_restart", False))),
        "enabled": bool(central.get("enabled", False)),
        "apply_safe": bool(central.get("apply_safe", False)),
        "blocked_failure_classes": set(str(x).upper() for x in central.get("blocked_failure_classes", [])),
    }
