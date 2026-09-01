from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import time
from typing import Any

from .logging_setup import log_event


class LegacyChildSupervisor:
    def __init__(self, bot_dir: Path, service: str, root: Path):
        self.bot_dir = bot_dir
        self.service = service
        self.root = root
        self.path = bot_dir / "legacy_main.py"
        self.proc: subprocess.Popen | None = None
        self.restarts = 0
        self.next_start = 0.0
        self.backoff = 2.0

    @property
    def available(self) -> bool:
        return self.path.is_file()

    def _spawn(self) -> subprocess.Popen:
        kwargs: dict[str, Any] = {"cwd": str(self.bot_dir)}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            # Keep the legacy child in the wrapper's process group so a managed
            # process-tree shutdown terminates both cleanly.
            kwargs["start_new_session"] = False
        proc = subprocess.Popen([sys.executable, str(self.path.name)], **kwargs)
        log_event("legacy_child_started", service=self.service, data={"pid": proc.pid}, root=self.root)
        return proc

    def tick(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "alive": False}
        now = time.monotonic()
        if self.proc is not None and self.proc.poll() is None:
            return {"available": True, "alive": True, "pid": self.proc.pid, "restarts": self.restarts}
        if self.proc is not None:
            code = self.proc.returncode
            log_event("legacy_child_exited", level="WARN", service=self.service,
                      data={"code": code, "restarts": self.restarts}, root=self.root)
            self.proc = None
            self.restarts += 1
            self.next_start = max(self.next_start, now + self.backoff)
            self.backoff = min(self.backoff * 2, 60.0)
        if now < self.next_start:
            return {"available": True, "alive": False, "restart_in_seconds": round(self.next_start-now, 1), "restarts": self.restarts}
        try:
            self.proc = self._spawn()
            self.backoff = 2.0
            self.next_start = 0.0
            return {"available": True, "alive": True, "pid": self.proc.pid, "restarts": self.restarts}
        except Exception as exc:
            self.next_start = now + self.backoff
            self.backoff = min(self.backoff * 2, 60.0)
            log_event("legacy_child_start_error", level="ERROR", service=self.service,
                      data={"type": type(exc).__name__, "error": str(exc)}, root=self.root)
            return {"available": True, "alive": False, "error": f"{type(exc).__name__}: {exc}"}

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:
                pass
        finally:
            log_event("legacy_child_stopped", service=self.service,
                      data={"pid": getattr(self.proc, "pid", None)}, root=self.root)
            self.proc = None
