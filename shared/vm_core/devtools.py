from __future__ import annotations
from pathlib import Path
import importlib.util
import shutil
import subprocess
import sys
from typing import Any
from .paths import project_root


def _available(name: str) -> bool:
    return bool(shutil.which(name) or importlib.util.find_spec(name))


def status() -> dict[str, Any]:
    return {
        "ruff": shutil.which("ruff") or ("python -m ruff" if importlib.util.find_spec("ruff") else None),
        "uv": shutil.which("uv") or ("python -m uv" if importlib.util.find_spec("uv") else None),
        "git": shutil.which("git"),
        "python": sys.executable,
    }


def install(apply: bool = False) -> dict[str, Any]:
    missing = [name for name in ("ruff", "uv") if not _available(name)]
    if not missing:
        return {"ok": True, "changed": False, "status": status()}
    cmd = [sys.executable, "-m", "pip", "install", "--user", *missing]
    if not apply:
        return {"ok": True, "dry_run": True, "missing": missing, "command": cmd}
    r = subprocess.run(cmd, text=True, capture_output=True)
    return {
        "ok": r.returncode == 0,
        "dry_run": False,
        "code": r.returncode,
        "requested": missing,
        "output": (r.stdout + r.stderr)[-10000:],
        "status": status(),
    }


def git_status(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    git = shutil.which("git")
    if not git:
        return {"available": False}
    inside = subprocess.run([git, "rev-parse", "--is-inside-work-tree"], cwd=root, text=True, capture_output=True)
    if inside.returncode != 0:
        return {"available": True, "repository": False}
    branch = subprocess.run([git, "branch", "--show-current"], cwd=root, text=True, capture_output=True).stdout.strip()
    remotes = subprocess.run([git, "remote", "-v"], cwd=root, text=True, capture_output=True).stdout.strip().splitlines()
    changes = [x for x in subprocess.run([git, "status", "--porcelain"], cwd=root, text=True, capture_output=True).stdout.splitlines() if x.strip()]
    return {"available": True, "repository": True, "branch": branch, "remote_lines": remotes, "working_tree_changes": len(changes)}
