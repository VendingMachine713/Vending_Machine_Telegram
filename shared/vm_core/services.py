from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time
from typing import Any
from .paths import project_root
from .manifests import discover_bots
from .db import PlatformDB
from .logging_setup import log_event
from .runtime_requirements import runtime_configuration_status

_PROCESS_HANDLES: dict[tuple[str, str], subprocess.Popen] = {}


def _handle_key(root: Path, name: str) -> tuple[str, str]:
    return (str(root.resolve()), name)


def _proc_exists(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
        )
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_file(root: Path, name: str) -> Path:
    return root / "state" / "pids" / f"{name}.pid"


def _read_pid(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _recently_started(row: dict[str, Any], seconds: int = 5) -> bool:
    raw = row.get("last_start_utc")
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() <= seconds
    except Exception:
        return False


def _known_live_pid(name: str, root: Path, settle_seconds: float = 0.0) -> int | None:
    key = _handle_key(root, name)
    proc = _PROCESS_HANDLES.get(key)
    if proc is not None:
        if proc.poll() is None:
            return proc.pid
        _PROCESS_HANDLES.pop(key, None)

    db = PlatformDB(root=root)
    db.init()
    row = next((r for r in db.services() if r["name"] == name), None)
    candidates: list[int] = []
    if row and row["pid"]:
        candidates.append(int(row["pid"]))
    file_pid = _read_pid(_pid_file(root, name))
    if file_pid and file_pid not in candidates:
        candidates.append(file_pid)

    deadline = time.monotonic() + max(0.0, settle_seconds)
    while True:
        for pid in candidates:
            if _proc_exists(pid):
                return pid
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)

    # Avoid racing Windows tasklist immediately after our own start.
    if row and row.get("pid") and _recently_started(row):
        return int(row["pid"])
    return None


def sync_services(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    for bot in discover_bots(root):
        db.upsert_service(bot.folder, bot.folder, bot.entrypoint, bot.launchers[0] if bot.launchers else None)
    rows = db.services()
    for row in rows:
        pid = _known_live_pid(row["name"], root)
        if pid:
            if row["pid"] != pid or row["runtime_status"] != "RUNNING":
                db.set_service_runtime(row["name"], "RUNNING", pid)
        elif row["pid"] and not _recently_started(row):
            db.set_service_runtime(row["name"], "STOPPED", None, stopped=True)
            pf = _pid_file(root, row["name"])
            if pf.exists():
                try:
                    pf.unlink()
                except OSError:
                    pass
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
        "guard": "vm_guard",
        "search": "universal_search",
        "relationship": "vm_relationship_manager",
        "relationships": "vm_relationship_manager",
        "admin": "admin_command_centre",
    }
    target = aliases.get(name_l)
    if target:
        for bot in bots:
            if bot.folder.lower() == target:
                return bot
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


def start_service(
    name: str,
    root: Path | None = None,
    dry_run: bool = True,
    force: bool = False,
    background: bool = False,
) -> dict[str, Any]:
    root = root or project_root()
    bot = _bot(name, root)
    if bot.classification == "PLACEHOLDER":
        return {"ok": False, "service": bot.folder, "reason": "PLANNED placeholder; runnable code is not installed."}
    live = _known_live_pid(bot.folder, root)
    if live:
        return {"ok": True, "service": bot.folder, "already_running": True, "pid": live}
    cfg = runtime_configuration_status(Path(bot.path))
    if not cfg["configured"]:
        return {"ok": False, "service": bot.folder, "reason": "Configuration required.", "missing_env_names": cfg["missing_env_names"]}
    cmd = _launch_command(bot)
    if not cmd:
        return {"ok": False, "service": bot.folder, "reason": "No runnable entrypoint or launcher detected."}
    if bot.entrypoint_confidence == "low" and not force:
        return {"ok": False, "service": bot.folder, "reason": "Entrypoint confidence is low; use --force after review.", "command": cmd}
    if dry_run:
        return {"ok": True, "dry_run": True, "background": background, "service": bot.folder, "cwd": bot.path, "command": cmd}

    kwargs: dict[str, Any] = {"cwd": bot.path}
    if os.name == "nt":
        if background:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            kwargs["stdin"] = subprocess.DEVNULL
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
        else:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    elif background:
        kwargs["start_new_session"] = True
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    proc = subprocess.Popen(cmd, **kwargs)
    _PROCESS_HANDLES[_handle_key(root, bot.folder)] = proc
    db = PlatformDB(root=root)
    db.init()
    db.upsert_service(bot.folder, bot.folder, bot.entrypoint, bot.launchers[0] if bot.launchers else None)
    db.set_service_runtime(bot.folder, "RUNNING", proc.pid, started=True)
    pf = _pid_file(root, bot.folder)
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(str(proc.pid), encoding="utf-8")
    log_event("service_started", service="platform", data={"service": bot.folder, "pid": proc.pid, "background": background}, root=root)
    time.sleep(0.05)
    if proc.poll() is not None:
        code = proc.returncode
        _PROCESS_HANDLES.pop(_handle_key(root, bot.folder), None)
        db.set_service_runtime(bot.folder, "FAILED", None, error=f"Exited immediately with code {code}")
        return {"ok": False, "service": bot.folder, "pid": proc.pid, "reason": f"Process exited immediately with code {code}", "command": cmd}
    return {"ok": True, "dry_run": False, "background": background, "service": bot.folder, "pid": proc.pid, "command": cmd}


def stop_service(name: str, root: Path | None = None, dry_run: bool = True) -> dict[str, Any]:
    root = root or project_root()
    bot = _bot(name, root)
    pid = _known_live_pid(bot.folder, root, settle_seconds=0.5)
    if not pid:
        return {"ok": True, "service": bot.folder, "already_stopped": True}
    if dry_run:
        return {"ok": True, "dry_run": True, "service": bot.folder, "pid": pid}

    key = _handle_key(root, bot.folder)
    proc = _PROCESS_HANDLES.get(key)
    if os.name == "nt":
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
        if r.returncode not in (0, 128):
            return {"ok": False, "service": bot.folder, "pid": pid, "error": (r.stdout + r.stderr).strip()}
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    if proc is not None:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
        _PROCESS_HANDLES.pop(key, None)

    db = PlatformDB(root=root)
    db.init()
    db.set_service_runtime(bot.folder, "STOPPED", None, stopped=True)
    pf = _pid_file(root, bot.folder)
    if pf.exists():
        try:
            pf.unlink()
        except OSError:
            pass
    log_event("service_stopped", service="platform", data={"service": bot.folder, "pid": pid}, root=root)
    return {"ok": True, "dry_run": False, "service": bot.folder, "pid": pid}


def restart_service(
    name: str,
    root: Path | None = None,
    dry_run: bool = True,
    force: bool = False,
    background: bool = False,
) -> dict[str, Any]:
    root = root or project_root()
    if dry_run:
        return {"ok": True, "dry_run": True, "stop": stop_service(name, root, True), "start": start_service(name, root, True, force, background)}
    stopped = stop_service(name, root, False)
    if not stopped.get("ok"):
        return {"ok": False, "stop": stopped}
    return {"ok": True, "stop": stopped, "start": start_service(name, root, False, force, background)}


def service_status(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or project_root()
    rows = sync_services(root)
    for row in rows:
        pid = row["pid"] or _read_pid(_pid_file(root, row["name"]))
        row["pid"] = pid
        row["process_alive"] = bool(_known_live_pid(row["name"], root))
        if row["process_alive"]:
            row["runtime_status"] = "RUNNING"
        elif row["runtime_status"] == "RUNNING" and not _recently_started(row):
            row["runtime_status"] = "STOPPED"
    return rows


def managed_services(root: Path | None = None) -> list[str]:
    root = root or project_root()
    names = []
    for bot in discover_bots(root):
        path = Path(bot.path) / "BOT_MANIFEST.json"
        if not path.is_file() or bot.classification == "PLACEHOLDER":
            continue
        try:
            life = (json.loads(path.read_text(encoding="utf-8")).get("lifecycle") or {})
            if life.get("auto_start"):
                names.append(bot.folder)
        except Exception:
            pass
    return names


def start_managed(root: Path | None = None, *, dry_run: bool = True, background: bool = True) -> list[dict[str, Any]]:
    root = root or project_root()
    return [start_service(name, root, dry_run=dry_run, background=background) for name in managed_services(root)]
