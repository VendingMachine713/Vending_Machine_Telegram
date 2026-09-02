from __future__ import annotations
from pathlib import Path
import json
from typing import Any
from .paths import project_root

DEFAULTS = {
    "schema_version": 1,
    "platform": {"name": "Vending Machine Telegram", "timezone": "Australia/Adelaide", "default_dry_run": True},
    "lifecycle": {"start_in_new_console_on_windows": True, "stop_timeout_seconds": 15},
    "backup": {"retention": 10, "include_bot_code": True, "include_databases": True, "include_sessions": False, "include_env_files": False},
    "support_bundle": {"include_recent_logs": True, "include_database_files": False, "include_session_files": False, "include_env_files": False},
}

def load_config(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    path = root / "config" / "vm_platform.json"
    if not path.is_file():
        return json.loads(json.dumps(DEFAULTS))
    data = json.loads(path.read_text(encoding="utf-8"))
    merged = json.loads(json.dumps(DEFAULTS))
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged
