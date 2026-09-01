from __future__ import annotations
from pathlib import Path
import json
import os
import subprocess
import sys
from typing import Any
from .paths import project_root
from .manifests import discover_bots
from .db import PlatformDB
from .logging_setup import log_event

def _proc_exists(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def sync_services(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or project_root()
    db = PlatformDB(root=root); db.init()
    for b in discover_bots(root):
        db.upsert_service(b.folder, b.folder, b.entrypoint, b.launchers[0] if b.launchers else None)
    rows = db.services()
    for row in rows:
        if row["pid"] and not _proc_exists(row["pid"]):
            db.set_service_runtime(row["name"], "STOPPED", None, stopped=True)
    return db.services()

def _bot(name: str, root: Path):
    name_l = name.lower()
    bots = discover_bots(root)
    exact = [b for b in bots if b.folder.lower() == name_l]
    if exact:
        return exact[0]
    partial = [b for b in bots if name_l in b.folder.lower()]
    if len(partial) == 1:
        return partial[0]
    aliases = {
        "autoposter": "smart_auto_poster_v2",
        "auto": "smart_auto_poster_v2",
        "poster": "smart_auto_poster_v2",
        "guard": "vm_guard",
        "search": "universal_search",
        "relationship": "vm_relationship_manager",
        "relationships": "vm_relationship_manager",
        "admin": "admin_command_centre",
    }
    target = aliases.get(name_l)
    if target:
        for b in bots:
            if b.folder.lower() == target:
                return b
    raise KeyError(f"Service not uniquely found: {name}")

def _launch_command(bot) -> list[str] | None:
    if bot.entrypoint:
        return [sys.executable, bot.entrypoint]
    if bot.launchers:
        launch = bot.launchers[0]
        ext = Path(launch).suffix.lower()
        if ext in {".bat", ".cmd"}:
            return ["cmd.exe", "/c", launch]
        if ext == ".ps1":
            return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", launch]
    return None

def start_service(name: str, root: Path | None = None, dry_run: bool = True, force: bool = False) -> dict[str, Any]:
    root = root or project_root()
    bot = _bot(name, root)
    cmd = _launch_command(bot)
    if not cmd:
        return {"ok": False, "service": bot.folder, "reason": "No runnable entrypoint or launcher detected."}
    if bot.entrypoint_confidence == "low" and not force:
        return {"ok": False, "service": bot.folder, "reason": "Entrypoint confidence is low; use --force after review.", "command": cmd}
    if dry_run:
        return {"ok": True, "dry_run": True, "service": bot.folder, "cwd": bot.path, "command": cmd}

    flags = 0
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        kwargs["creationflags"] = flags
    proc = subprocess.Popen(cmd, cwd=bot.path, **kwargs)
    db = PlatformDB(root=root); db.init()
    db.upsert_service(bot.folder, bot.folder, bot.entrypoint, bot.launchers[0] if bot.launchers else None)
    db.set_service_runtime(bot.folder, "RUNNING", proc.pid, started=True)
    (root / "state" / "pids" / f"{bot.folder}.pid").write_text(str(proc.pid), encoding="utf-8")
    log_event("service_started", service="platform", data={"service": bot.folder, "pid": proc.pid}, root=root)
    return {"ok": True, "dry_run": False, "service": bot.folder, "pid": proc.pid, "command": cmd}

def stop_service(name: str, root: Path | None = None, dry_run: bool = True) -> dict[str, Any]:
    root = root or project_root()
    bot = _bot(name, root)
    db = PlatformDB(root=root); db.init()
    row = next((r for r in db.services() if r["name"] == bot.folder), None)
    pid = row["pid"] if row else None
    if not pid:
        pid_file = root / "state" / "pids" / f"{bot.folder}.pid"
        if pid_file.is_file():
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
            except ValueError:
                pid = None
    if not pid:
        return {"ok": True, "service": bot.folder, "already_stopped": True}
    if dry_run:
        return {"ok": True, "dry_run": True, "service": bot.folder, "pid": pid}
    if os.name == "nt":
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T"], capture_output=True, text=True)
        if r.returncode not in (0, 128):
            return {"ok": False, "service": bot.folder, "pid": pid, "error": (r.stdout + r.stderr).strip()}
    else:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
    db.set_service_runtime(bot.folder, "STOPPED", None, stopped=True)
    pid_file = root / "state" / "pids" / f"{bot.folder}.pid"
    if pid_file.exists():
        pid_file.unlink()
    log_event("service_stopped", service="platform", data={"service": bot.folder, "pid": pid}, root=root)
    return {"ok": True, "dry_run": False, "service": bot.folder, "pid": pid}

def restart_service(name: str, root: Path | None = None, dry_run: bool = True, force: bool = False) -> dict[str, Any]:
    root = root or project_root()
    if dry_run:
        return {"ok": True, "dry_run": True, "stop": stop_service(name, root, True), "start": start_service(name, root, True, force)}
    stop = stop_service(name, root, False)
    if not stop.get("ok"):
        return {"ok": False, "stop": stop}
    return {"ok": True, "stop": stop, "start": start_service(name, root, False, force)}

def service_status(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or project_root()
    rows = sync_services(root)
    for row in rows:
        row["process_alive"] = _proc_exists(row["pid"])
        if row["process_alive"]:
            row["runtime_status"] = "RUNNING"
        elif row["runtime_status"] == "RUNNING":
            row["runtime_status"] = "STOPPED"
    return rows

def run_service_cli(name: str, args: list[str], root: Path | None = None, timeout: int = 30) -> dict[str, Any]:
    """Run one service's Python entrypoint as a bounded subprocess.

    This is the shared VM Core bridge used by control surfaces such as the
    standalone Admin Command Centre. It deliberately uses argv lists with
    shell=False semantics, captures output, and applies a timeout so callers do
    not need to import another bot's internal Python modules.
    """
    root = root or project_root()
    bot = _bot(name, root)
    if not bot.entrypoint:
        return {"ok": False, "service": bot.folder, "reason": "Service has no Python entrypoint."}
    cmd = [sys.executable, bot.entrypoint, *[str(x) for x in args]]
    try:
        proc = subprocess.run(cmd, cwd=bot.path, capture_output=True, text=True, timeout=max(1, int(timeout)), shell=False)
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "service": bot.folder,
            "timeout": True,
            "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
        }
    except OSError as exc:
        return {"ok": False, "service": bot.folder, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": proc.returncode == 0,
        "service": bot.folder,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-2000:],
    }
