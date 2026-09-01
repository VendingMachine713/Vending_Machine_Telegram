from __future__ import annotations
from pathlib import Path
import os
import subprocess
from typing import Any
from .paths import project_root

TASK_NAME = "VendingMachineTelegram"
STARTUP_VBS = "VendingMachineTelegram.vbs"


def _startup_path() -> Path | None:
    appdata = os.getenv("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / STARTUP_VBS


def status(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    if os.name != "nt":
        return {"supported": False, "platform": os.name, "task_name": TASK_NAME, "registered": False}
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
        text=True, capture_output=True
    )
    startup = _startup_path()
    task_registered = r.returncode == 0
    startup_registered = bool(startup and startup.is_file())
    method = "task_scheduler" if task_registered else ("startup_folder" if startup_registered else "none")
    return {
        "supported": True,
        "task_name": TASK_NAME,
        "registered": task_registered or startup_registered,
        "method": method,
        "task_registered": task_registered,
        "startup_fallback_registered": startup_registered,
        "startup_fallback_path": str(startup) if startup else None,
        "query_code": r.returncode,
        "details": r.stdout[-8000:] if task_registered else (r.stdout + r.stderr)[-4000:],
        "runner": str(root / "START_VM_MANAGED.bat"),
    }
