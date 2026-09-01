from __future__ import annotations
from pathlib import Path
import importlib.util
import re
import shutil
import subprocess
import sys
from typing import Any
from .paths import project_root
from .manifests import discover_bots

REQ_NAME = re.compile(r"^\s*([A-Za-z0-9_.-]+)")

def environment_report(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "uv": shutil.which("uv"),
        "ruff": shutil.which("ruff"),
        "git": shutil.which("git"),
        "pip": shutil.which("pip") or "python -m pip",
    }

def requirements_inventory(root: Path | None = None) -> dict[str, list[str]]:
    root = root or project_root()
    out = {}
    for bot in discover_bots(root):
        if not bot.requirements:
            out[bot.folder] = []
            continue
        path = Path(bot.path) / bot.requirements
        reqs = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = REQ_NAME.match(line)
            if m:
                reqs.append(m.group(1))
        out[bot.folder] = reqs
    return out

def pip_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-m", "pip", "check"], text=True, capture_output=True)
    return r.returncode, (r.stdout + r.stderr).strip()

def setup_dependencies(root: Path | None = None, apply: bool = False) -> list[dict[str, Any]]:
    root = root or project_root()
    actions = []
    for bot in discover_bots(root):
        if not bot.requirements:
            continue
        req = Path(bot.path) / bot.requirements
        cmd = [sys.executable, "-m", "pip", "install", "-r", str(req)]
        if not apply:
            actions.append({"bot": bot.folder, "action": "would_install", "command": cmd})
            continue
        r = subprocess.run(cmd, cwd=Path(bot.path))
        actions.append({"bot": bot.folder, "action": "installed" if r.returncode == 0 else "failed", "code": r.returncode})
    return actions
