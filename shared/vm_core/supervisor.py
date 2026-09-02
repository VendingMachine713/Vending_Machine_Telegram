from __future__ import annotations
from pathlib import Path
import json
import time
from typing import Any
from .paths import project_root
from .manifests import discover_bots
from .services import service_status, start_service
from .events import emit
from .logging_setup import log_event


def _policy(bot_dir: Path) -> dict[str, Any]:
    path = bot_dir / "BOT_MANIFEST.json"
    if not path.is_file():
        return {"auto_start": False, "auto_restart": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        life = data.get("lifecycle") or {}
        return {
            "auto_start": bool(life.get("auto_start", False)),
            "auto_restart": bool(life.get("auto_restart", False)),
        }
    except Exception:
        return {"auto_start": False, "auto_restart": False}


def supervise_once(root: Path | None = None, apply: bool = False) -> list[dict[str, Any]]:
    root = root or project_root()
    states = {r["name"]: r for r in service_status(root)}
    actions = []
    for bot in discover_bots(root):
        if bot.classification == "PLACEHOLDER":
            actions.append({"service": bot.folder, "action": "none", "reason": "PLANNED placeholder; no runnable service installed."})
            continue
        policy = _policy(Path(bot.path))
        state = states.get(bot.folder, {})
        alive = bool(state.get("process_alive"))
        desired = policy["auto_start"] or policy["auto_restart"]
        if desired and not alive:
            result = start_service(bot.folder, root, dry_run=not apply)
            actions.append({"service": bot.folder, "action": "restart" if policy["auto_restart"] else "start", "result": result})
            emit("supervisor.recovery_requested", "supervisor", {"service": bot.folder, "applied": apply}, root)
            log_event("supervisor_recovery", level="WARN", data={"service": bot.folder, "applied": apply}, root=root)
        else:
            actions.append({"service": bot.folder, "action": "none", "alive": alive, "policy": policy})

    # Intelligence refresh is deliberately isolated from recovery control. A
    # collector/read-model problem must never prevent normal supervisor actions.
    try:
        from .intelligence import materialize_intelligence
        materialize_intelligence(root)
    except Exception as exc:
        emit(
            "incident.intelligence_refresh_failed",
            "supervisor",
            {"summary": "VM Intelligence refresh failed", "error_type": type(exc).__name__},
            root,
            severity="WARNING",
            subject_type="service",
            subject_id="VM_Intelligence",
        )
        log_event(
            "intelligence_refresh_failed",
            level="WARN",
            data={"error_type": type(exc).__name__},
            root=root,
        )
    return actions


def supervise_loop(root: Path | None = None, apply: bool = False, interval_seconds: int = 60) -> None:
    root = root or project_root()
    while True:
        supervise_once(root, apply=apply)
        time.sleep(max(10, interval_seconds))
