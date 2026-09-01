from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
import time
import secrets
from datetime import datetime, timezone
from pathlib import Path


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pid_alive_windows(pid: int) -> bool:
    """Return whether *pid* appears alive without using os.kill on Windows.

    os.kill(pid, 0) is not as predictable on Windows as it is on POSIX and can
    interact poorly with process/security APIs during test cleanup. Querying a
    process handle is fast, non-destructive, and avoids that code path.
    """
    if pid <= 0:
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        open_process.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid))
        if handle:
            close_handle(handle)
            return True

        # ERROR_ACCESS_DENIED means a process likely exists but cannot be queried.
        return ctypes.get_last_error() == 5
    except Exception:
        # Fail safe: if Windows process probing itself fails, do not declare an
        # arbitrary PID alive. RuntimeLock's grace period still protects a lock
        # that was only just created and has not written metadata yet.
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
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
    """Cross-platform single-runtime lock for Telegram session safety.

    V3.0 used an exclusive lock *file*. On Windows, an interrupted exclusive
    open could leave a transient handle that blocked TemporaryDirectory cleanup.
    V3.0.1 uses an atomic lock *directory* instead. Directory creation/removal
    has no long-lived file descriptor and behaves consistently on Windows.

    Existing V3.0 lock files remain readable/reclaimable for compatibility.
    """

    OWNER_FILE = "owner.json"
    # If a just-created directory has no readable owner metadata, another
    # process may still be writing it. Never reclaim such a lock immediately.
    UNINITIALIZED_GRACE_SECONDS = 30.0

    def __init__(self, path: Path):
        self.path = Path(path)
        self.token = secrets.token_hex(12)
        self.acquired = False

    @property
    def _owner_path(self) -> Path:
        if self.path.is_dir():
            return self.path / self.OWNER_FILE
        return self.path

    def _read_existing(self) -> dict:
        try:
            return json.loads(self._owner_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _lock_age_seconds(self) -> float | None:
        try:
            return max(0.0, time.time() - self.path.stat().st_mtime)
        except OSError:
            return None

    def _remove_stale(self) -> None:
        try:
            if self.path.is_dir():
                shutil.rmtree(self.path)
            else:
                self.path.unlink()
        except FileNotFoundError:
            pass

    def _create_lock_directory(self, payload: dict) -> None:
        os.mkdir(self.path)
        try:
            owner = self.path / self.OWNER_FILE
            owner.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except BaseException:
            # Do not strand a directory lock if metadata creation is interrupted.
            try:
                shutil.rmtree(self.path)
            except OSError:
                pass
            raise

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "token": self.token,
            "started_at": _utcnow(),
            "lock_format": 2,
        }

        # Three attempts allow a race where another process removes a stale lock
        # between our read and reclaim without turning the condition into a hang.
        for _ in range(3):
            try:
                self._create_lock_directory(payload)
                self.acquired = True
                return self
            except FileExistsError:
                existing = self._read_existing()
                pid = int(existing.get("pid") or 0)
                if pid and _pid_alive(pid):
                    raise RuntimeError(
                        f"Another Smart Auto Poster Telegram runtime is already active "
                        f"(PID {pid}). Stop it before starting scan/worker/run."
                    )

                if not pid:
                    age = self._lock_age_seconds()
                    if age is not None and age < self.UNINITIALIZED_GRACE_SECONDS:
                        raise RuntimeError(
                            "Another Smart Auto Poster runtime appears to be starting "
                            f"(lock age {age:.1f}s). Try again shortly."
                        )

                # Stale lock: recorded process is gone (or metadata is old and
                # invalid). Reclaim it, then retry the atomic mkdir.
                self._remove_stale()
            except NotADirectoryError:
                # Compatibility path: V3.0 may have left an old lock file.
                existing = self._read_existing()
                pid = int(existing.get("pid") or 0)
                if pid and _pid_alive(pid):
                    raise RuntimeError(
                        f"Another Smart Auto Poster Telegram runtime is already active "
                        f"(PID {pid}). Stop it before starting scan/worker/run."
                    )
                self._remove_stale()

        raise RuntimeError(f"Could not acquire runtime lock: {self.path}")

    def release(self):
        if not self.acquired:
            return
        existing = self._read_existing()
        if existing.get("token") == self.token:
            try:
                if self.path.is_dir():
                    shutil.rmtree(self.path)
                else:
                    self.path.unlink()
            except FileNotFoundError:
                pass
        self.acquired = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
