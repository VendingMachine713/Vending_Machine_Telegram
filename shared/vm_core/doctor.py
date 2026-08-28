from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import json
import os
import platform
import shutil
import sqlite3
import sys
from typing import Any

from .manifests import discover_bots
from .paths import project_root


@dataclass
class Check:
    category: str
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _check_import(name: str) -> Check:
    found = importlib.util.find_spec(name) is not None
    return Check(
        "dependencies",
        name,
        "PASS" if found else "INFO",
        "installed" if found else "not installed in the current Python environment",
    )


def _sqlite_integrity(path: Path) -> Check:
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            row = conn.execute("PRAGMA integrity_check;").fetchone()
        finally:
            conn.close()
        result = row[0] if row else "no result"
        return Check(
            "database",
            path.name,
            "PASS" if result == "ok" else "WARN",
            result,
        )
    except sqlite3.Error as exc:
        return Check("database", path.name, "WARN", f"{type(exc).__name__}: {exc}")


def run_doctor(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    checks: list[Check] = []

    checks.append(Check(
        "platform",
        "project_root",
        "PASS" if root.is_dir() else "FAIL",
        str(root),
    ))
    checks.append(Check(
        "platform",
        "bots_directory",
        "PASS" if (root / "bots").is_dir() else "FAIL",
        str(root / "bots"),
    ))
    checks.append(Check(
        "runtime",
        "python",
        "PASS" if sys.version_info >= (3, 11) else "WARN",
        f"{platform.python_version()} | {sys.executable}",
    ))
    checks.append(Check(
        "runtime",
        "operating_system",
        "PASS",
        f"{platform.system()} {platform.release()}",
    ))

    usage = shutil.disk_usage(root)
    free_gb = usage.free / (1024 ** 3)
    checks.append(Check(
        "runtime",
        "disk_free",
        "PASS" if free_gb >= 2 else "WARN",
        f"{free_gb:.1f} GiB free",
    ))
    checks.append(Check(
        "runtime",
        "root_write_access",
        "PASS" if os.access(root, os.W_OK) else "WARN",
        "writable" if os.access(root, os.W_OK) else "not writable",
    ))

    # Common VM dependencies. Missing packages are informational because not every bot needs all.
    for package in ("telethon", "telegram", "dotenv", "tzdata"):
        checks.append(_check_import(package))

    bots = discover_bots(root)
    if not bots:
        checks.append(Check("bots", "discovery", "WARN", "No bot folders discovered."))

    for bot in bots:
        if bot.entrypoint:
            detail = f"{bot.entrypoint} (confidence={bot.entrypoint_confidence})"
            checks.append(Check("bot", f"{bot.folder}:entrypoint", "PASS", detail))
        else:
            checks.append(Check("bot", f"{bot.folder}:entrypoint", "WARN", "No likely entrypoint detected."))

        if bot.requirements or bot.pyproject:
            detail = bot.pyproject or bot.requirements or ""
            checks.append(Check("bot", f"{bot.folder}:dependencies", "PASS", detail))
        else:
            checks.append(Check(
                "bot",
                f"{bot.folder}:dependencies",
                "INFO",
                "No requirements.txt or pyproject.toml at bot root.",
            ))

        if bot.nested_duplicate_folder:
            checks.append(Check(
                "bot",
                f"{bot.folder}:nested_duplicate",
                "WARN",
                f"Nested folder '{bot.folder}/{bot.folder}' detected; review before future updates.",
            ))

    # Session names only; no auth material is read or copied.
    sessions = sorted(root.rglob("*.session"))
    checks.append(Check(
        "telegram",
        "session_files",
        "PASS" if sessions else "INFO",
        f"{len(sessions)} session file(s) detected; contents not inspected.",
    ))

    # Validate JSON syntax without exposing values.
    json_files = [
        p for p in root.rglob("*.json")
        if "diagnostics" not in p.parts and ".git" not in p.parts
    ]
    invalid_json = 0
    for path in json_files[:250]:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            invalid_json += 1
    checks.append(Check(
        "config",
        "json_syntax",
        "PASS" if invalid_json == 0 else "WARN",
        f"{len(json_files[:250])} checked, {invalid_json} invalid",
    ))

    # SQLite integrity. Limit count to keep doctor quick on large trees.
    db_files: list[Path] = []
    for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
        db_files.extend(root.rglob(pattern))
    for db in sorted(set(db_files))[:30]:
        checks.append(_sqlite_integrity(db))

    counts = {
        status: sum(1 for c in checks if c.status == status)
        for status in ("PASS", "INFO", "WARN", "FAIL")
    }

    return {
        "schema_version": 1,
        "vm_core_version": "0.2.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "bot_count": len(bots),
        "checks": [c.to_dict() for c in checks],
        "summary": counts,
    }


def write_diagnostics(report: dict[str, Any], root: Path | None = None) -> tuple[Path, Path]:
    root = root or project_root()
    diagnostics = root / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)

    json_path = diagnostics / "latest_diagnostic.json"
    txt_path = diagnostics / "latest_diagnostic.txt"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    lines = [
        "=" * 72,
        "VM DOCTOR",
        "=" * 72,
        f"Generated: {report['generated_at_utc']}",
        f"Root:      {report['project_root']}",
        f"Bots:      {report['bot_count']}",
        "",
    ]
    for check in report["checks"]:
        lines.append(
            f"[{check['status']:<4}] "
            f"{check['category']}/{check['name']}: {check['detail']}"
        )

    lines += [
        "",
        "-" * 72,
        "SUMMARY",
        "-" * 72,
    ]
    for key in ("PASS", "INFO", "WARN", "FAIL"):
        lines.append(f"{key}: {report['summary'][key]}")
    lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, txt_path
