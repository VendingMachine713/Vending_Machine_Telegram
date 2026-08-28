from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # A process exists but we do not have permission to signal it.
        return True
    except OSError:
        return False


class RuntimeLock:
    """Simple process lock preventing concurrent Telegram runtimes.

    The lock protects the Telethon session files and outbound queue from accidental
    multi-process use. A stale lock is reclaimed only when its recorded PID is no
    longer alive.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.token = secrets.token_hex(12)
        self.acquired = False

    def _read_existing(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "token": self.token,
            "started_at": _utcnow(),
        }
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, json.dumps(payload, indent=2).encode("utf-8"))
                finally:
                    os.close(fd)
                self.acquired = True
                return self
            except FileExistsError:
                existing = self._read_existing()
                pid = int(existing.get("pid") or 0)
                if _pid_alive(pid):
                    raise RuntimeError(
                        f"Another Smart Auto Poster Telegram runtime is already active "
                        f"(PID {pid}). Stop it before starting scan/worker/run."
                    )
                # Stale lock: process is gone. Reclaim it and retry once.
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
        raise RuntimeError(f"Could not acquire runtime lock: {self.path}")

    def release(self):
        if not self.acquired:
            return
        existing = self._read_existing()
        if existing.get("token") == self.token:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self.acquired = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
