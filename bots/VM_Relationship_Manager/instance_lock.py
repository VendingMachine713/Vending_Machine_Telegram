from __future__ import annotations

import os
from pathlib import Path


class AlreadyRunningError(RuntimeError):
    pass


class SingleInstanceLock:
    """Hold an OS-backed non-blocking lock for the lifetime of the process."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                # Ensure there is one byte to lock.
                if not handle.read(1):
                    handle.seek(0)
                    handle.write("0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise AlreadyRunningError("another VM Relationship Manager instance already holds the runtime lock") from exc
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise AlreadyRunningError("another VM Relationship Manager instance already holds the runtime lock") from exc

            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
            self.handle = handle
            return self
        except Exception:
            handle.close()
            raise

    def release(self):
        handle = self.handle
        if not handle:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                handle.close()
            finally:
                self.handle = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
