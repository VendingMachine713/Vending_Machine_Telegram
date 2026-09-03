from __future__ import annotations
from pathlib import Path
import json
from typing import Any
from .paths import project_root

DEFAULTS = {
    "schema_version": 1,
    "platform": {
        "name": "Vending Machine Telegram",
        "timezone": "Australia/Adelaide",
        "default_dry_run": True,
    },
    "lifecycle": {
        "start_in_new_console_on_windows": True,
        "stop_timeout_seconds": 15,
    },
    "backup": {
        "retention": 10,
        "include_bot_code": True,
        "include_databases": True,
        "include_sessions": False,
        "include_env_files": False,
    },
    "support_bundle": {
        "include_recent_logs": True,
        "include_database_files": False,
        "include_session_files": False,
        "include_env_files": False,
    },
}

def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value))

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = _clone(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = _clone(value)
    return result

def validate_config(config: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    schema = config.get("schema_version")
    if not isinstance(schema, int) or schema < 1:
        issues.append({
            "severity": "ERROR",
            "code": "CONFIG_SCHEMA_INVALID",
            "detail": "schema_version must be an integer >= 1",
        })

    platform = config.get("platform")
    if not isinstance(platform, dict):
        issues.append({
            "severity": "ERROR",
            "code": "CONFIG_PLATFORM_INVALID",
            "detail": "platform must be an object",
        })
    else:
        if not isinstance(platform.get("name"), str) or not platform["name"].strip():
            issues.append({
                "severity": "ERROR",
                "code": "CONFIG_PLATFORM_NAME_INVALID",
                "detail": "platform.name must be a non-empty string",
            })
        if not isinstance(platform.get("timezone"), str) or not platform["timezone"].strip():
            issues.append({
                "severity": "ERROR",
                "code": "CONFIG_TIMEZONE_INVALID",
                "detail": "platform.timezone must be a non-empty string",
            })
        if not isinstance(platform.get("default_dry_run"), bool):
            issues.append({
                "severity": "ERROR",
                "code": "CONFIG_DRY_RUN_INVALID",
                "detail": "platform.default_dry_run must be boolean",
            })

    lifecycle = config.get("lifecycle")
    if not isinstance(lifecycle, dict):
        issues.append({
            "severity": "ERROR",
            "code": "CONFIG_LIFECYCLE_INVALID",
            "detail": "lifecycle must be an object",
        })
    else:
        timeout = lifecycle.get("stop_timeout_seconds")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
            issues.append({
                "severity": "ERROR",
                "code": "CONFIG_STOP_TIMEOUT_INVALID",
                "detail": "lifecycle.stop_timeout_seconds must be an integer >= 1",
            })

    backup = config.get("backup")
    if not isinstance(backup, dict):
        issues.append({
            "severity": "ERROR",
            "code": "CONFIG_BACKUP_INVALID",
            "detail": "backup must be an object",
        })
    else:
        retention = backup.get("retention")
        if not isinstance(retention, int) or isinstance(retention, bool) or retention < 1:
            issues.append({
                "severity": "ERROR",
                "code": "CONFIG_BACKUP_RETENTION_INVALID",
                "detail": "backup.retention must be an integer >= 1",
            })
        if backup.get("include_env_files") is True:
            issues.append({
                "severity": "WARN",
                "code": "CONFIG_BACKUP_ENV_INCLUDED",
                "detail": "backup.include_env_files is enabled; review secret-handling policy",
            })

    support = config.get("support_bundle")
    if not isinstance(support, dict):
        issues.append({
            "severity": "ERROR",
            "code": "CONFIG_SUPPORT_BUNDLE_INVALID",
            "detail": "support_bundle must be an object",
        })
    else:
        for key in ("include_env_files", "include_session_files"):
            if support.get(key) is True:
                issues.append({
                    "severity": "ERROR",
                    "code": "CONFIG_SUPPORT_SECRET_EXPOSURE",
                    "detail": f"support_bundle.{key} must remain false",
                })

    return issues

def load_config(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    path = root / "config" / "vm_platform.json"
    if not path.is_file():
        return _clone(DEFAULTS)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("config/vm_platform.json must contain a JSON object")
    return _deep_merge(DEFAULTS, data)
