from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import project_root

DEFAULT_POLICY: dict[str, Any] = {
    "enabled": False,
    "apply_safe": False,
    "interval_seconds": 60,
    "max_actions_per_pass": 1,
    "services": {},
}


def policy_path(root: Path | None = None) -> Path:
    root = root or project_root()
    return root / "config" / "vm_recovery_policy.json"


def load_recovery_policy(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    path = policy_path(root)
    policy = dict(DEFAULT_POLICY)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                policy.update({k: v for k, v in raw.items() if k != "services"})
                if isinstance(raw.get("services"), dict):
                    policy["services"] = dict(raw["services"])
        except Exception:
            policy["invalid"] = True
    policy["interval_seconds"] = max(15, int(policy.get("interval_seconds", 60)))
    policy["max_actions_per_pass"] = max(0, min(3, int(policy.get("max_actions_per_pass", 1))))
    policy["enabled"] = bool(policy.get("enabled", False))
    policy["apply_safe"] = bool(policy.get("apply_safe", False))
    return policy


def service_policy(service: str, manifest_policy: dict[str, bool], root: Path | None = None) -> dict[str, bool]:
    """Resolve one service's recovery policy from one central configuration file.

    A central opt-in is honored only for manifests marked managed_by_vm. This
    avoids per-bot PowerShell configuration while retaining an explicit service
    allowlist and safe default-off behavior.
    """
    policy = load_recovery_policy(root)
    override = (policy.get("services") or {}).get(service) or {}
    if not isinstance(override, dict):
        override = {}
    managed = bool(manifest_policy.get("managed_by_vm", False))
    return {
        "managed_by_vm": managed,
        "auto_start": bool(manifest_policy.get("auto_start", False) or (managed and override.get("auto_start", False))),
        "auto_restart": bool(manifest_policy.get("auto_restart", False) or (managed and override.get("auto_restart", False))),
    }
