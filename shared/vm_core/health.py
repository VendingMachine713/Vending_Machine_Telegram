from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from .db import PlatformDB
from .health_contract import service_health_record
from .manifests import discover_bots
from .paths import project_root
from .runtime_requirements import runtime_configuration_status
from .service_adapters import adapter_status
from .services import service_status


def _db_check(path: Path) -> str:
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
            return row[0] if row else "no result"
        finally:
            con.close()
    except sqlite3.Error as exc:
        return f"ERROR: {exc}"


def run_health(root: Path | None = None) -> list[dict[str, Any]]:
    """Evaluate services and persist/return the standard VM health contract."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    runtime = {row["name"]: row for row in service_status(root)}
    out: list[dict[str, Any]] = []

    for bot in discover_bots(root):
        cfg = runtime_configuration_status(Path(bot.path))
        adapter = adapter_status(bot)
        details: dict[str, Any] = {
            "classification": bot.classification,
            "entrypoint": bot.entrypoint,
            "entrypoint_confidence": bot.entrypoint_confidence,
            "manifest": bot.manifest_present,
            "runtime_status": runtime.get(bot.folder, {}).get("runtime_status", "UNKNOWN"),
            "process_alive": runtime.get(bot.folder, {}).get("process_alive", False),
            "configuration": cfg,
            "databases": {},
            "adapter": adapter,
        }
        for rel in bot.databases[:20]:
            details["databases"][rel] = _db_check(Path(bot.path) / rel)

        bad_database = any(value != "ok" for value in details["databases"].values())
        if bot.classification == "PLACEHOLDER":
            status = "PLANNED"
        elif not cfg["configured"]:
            status = "CONFIG_REQUIRED"
        elif bad_database:
            status = "DEGRADED"
        elif not bot.entrypoint and not bot.launchers:
            status = "DEGRADED"
        elif adapter["status"] == "EVIDENCE_REQUIRED":
            status = "DEGRADED"
        elif details["process_alive"]:
            status = "ALIVE"
        else:
            status = "READY"

        record = service_health_record(bot.folder, status, detail=details)
        db.set_health(bot.folder, record["status"], details)
        out.append(record)

    return out
