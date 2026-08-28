from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess
import sys
from typing import Any

from .paths import project_root
from .backup import create_backup
from .manifests import write_inventory, refresh_bot_manifests, build_inventory
from .inspect import write_structure_report
from .duplicates import write_duplicate_report, analyze_nested_duplicates
from .registry import sync_accounts, sync_destinations, registry_summary
from .health import run_health
from .doctor import run_doctor, write_diagnostics
from .dependencies import environment_report
from .checks import full_check
from .supervisor import supervise_once

def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

def _run_platform_tests(root: Path) -> dict[str, Any]:
    r = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(root / "tests"), "-p", "test_*.py", "-v"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    return {
        "ok": r.returncode == 0,
        "code": r.returncode,
        "output": (r.stdout + r.stderr)[-30000:],
    }

def run_full_validation(root: Path | None = None, *, backup_first: bool = True) -> dict[str, Any]:
    root = root or project_root()
    diag = root / "diagnostics"
    diag.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()

    backup_path = str(create_backup(root, kind="validation")) if backup_first else None
    refresh = refresh_bot_manifests(root, write=True)
    inventory_path = str(write_inventory(root))
    structure_json, structure_txt = write_structure_report(root)
    duplicate_json, duplicate_txt = write_duplicate_report(root)

    registry_result = {
        "accounts_synced": sync_accounts(root),
        "destinations": sync_destinations(root),
        "summary": registry_summary(root),
    }
    _write_json(diag / "registry_report.json", registry_result)

    tests = _run_platform_tests(root)
    _write_json(diag / "platform_tests_report.json", tests)

    health = run_health(root)
    _write_json(diag / "health_report.json", health)

    doctor = run_doctor(root)
    write_diagnostics(doctor, root)

    env = environment_report(root)
    _write_json(diag / "environment_report.json", env)

    preflight = full_check(root, test_code=0 if tests["ok"] else 1)
    _write_json(diag / "preflight_report.json", preflight)

    supervisor = supervise_once(root, apply=False)
    _write_json(diag / "supervisor_preview.json", supervisor)

    inv = build_inventory(root)
    duplicate_data = analyze_nested_duplicates(root)

    summary = {
        "schema_version": 1,
        "vm_core_version": "1.2.0",
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "backup": backup_path,
        "bots_total": inv["bot_count"],
        "bots_runnable": inv["runnable_count"],
        "bots_planned": inv["planned_count"],
        "manifest_refresh": refresh,
        "platform_tests_ok": tests["ok"],
        "health": {item["service"]: item["status"] for item in health},
        "doctor_summary": doctor["summary"],
        "invalid_json_files": doctor.get("invalid_json_files", []),
        "preflight_ok": bool(preflight.get("ok")),
        "registry": registry_result,
        "nested_duplicate_bots": [b["bot"] for b in duplicate_data["bots"]],
        "supervisor_actions": supervisor,
        "artifacts": {
            "inventory": inventory_path,
            "structure": str(structure_txt),
            "duplicates": str(duplicate_txt),
        },
    }
    _write_json(diag / "full_validation.json", summary)

    lines = [
        "=" * 72,
        "VM FULL PLATFORM VALIDATION",
        "=" * 72,
        f"VM Core:          1.2.0",
        f"Bots:             {summary['bots_total']} total | {summary['bots_runnable']} runnable | {summary['bots_planned']} planned",
        f"Platform tests:   {'PASS' if summary['platform_tests_ok'] else 'FAIL'}",
        f"Pre-flight:       {'PASS' if summary['preflight_ok'] else 'REVIEW'}",
        f"Doctor failures:  {summary['doctor_summary']['FAIL']}",
        f"Doctor warnings:  {summary['doctor_summary']['WARN']}",
        f"Destinations:     {summary['registry']['summary']['destinations']}",
        f"Accounts:         {summary['registry']['summary']['accounts']}",
        f"Backup:           {backup_path or 'not requested'}",
        "",
        "SERVICE HEALTH",
        "-" * 72,
    ]
    for service, status in summary["health"].items():
        lines.append(f"{status:<10} {service}")
    if summary["invalid_json_files"]:
        lines += ["", "INVALID JSON", "-" * 72]
        for item in summary["invalid_json_files"]:
            lines.append(f"{item['path']}: {item['error']}")
    if summary["nested_duplicate_bots"]:
        lines += ["", "NESTED DUPLICATES", "-" * 72]
        for name in summary["nested_duplicate_bots"]:
            lines.append(name)
    txt = diag / "full_validation.txt"
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
