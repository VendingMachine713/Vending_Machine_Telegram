from __future__ import annotations

from pathlib import Path

from instance_lock import AlreadyRunningError, SingleInstanceLock


def main() -> int:
    runtime = Path(__file__).resolve().parent / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    lock = SingleInstanceLock(runtime / "vm_relationship_manager.instance.lock")
    try:
        lock.acquire()
    except AlreadyRunningError:
        print("[X] VM Relationship Manager is currently running.")
        print("[X] Stop the running/manual/background instance before applying an update.")
        return 12
    finally:
        # release() is safe even when acquire() did not succeed.
        try:
            lock.release()
        except Exception:
            pass

    print("[+] Update runtime guard: no active Relationship Manager instance detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
