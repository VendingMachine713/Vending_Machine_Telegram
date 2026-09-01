import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from smart_autoposter.db import Database
from smart_autoposter.runtime_lock import RuntimeLock
from smart_autoposter.safety import SafetyController


class SafetyAndRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "db.sqlite3")
        self.db.init()

    def tearDown(self):
        self.tmp.cleanup()

    def test_manual_pause_and_resume(self):
        safety = SafetyController(self.db, failure_threshold=3, window_minutes=10, pause_minutes=30, failure_ratio=0.8)
        state = safety.pause("maintenance", manual=True)
        self.assertTrue(state.paused)
        self.assertTrue(state.manual)
        state = safety.resume()
        self.assertFalse(state.paused)

    def test_circuit_breaker_trips_on_failure_burst(self):
        safety = SafetyController(self.db, failure_threshold=3, window_minutes=10, pause_minutes=30, failure_ratio=0.75)
        for i in range(3):
            self.db.event("WARNING", "send_failure", f"failure {i}")
        self.db.event("INFO", "send_success", "success")
        state = safety.evaluate()
        self.assertTrue(state.paused)
        self.assertFalse(state.manual)
        self.assertIn("Circuit breaker", state.reason)

    def test_circuit_breaker_does_not_trip_below_ratio(self):
        safety = SafetyController(self.db, failure_threshold=3, window_minutes=10, pause_minutes=30, failure_ratio=0.8)
        for i in range(3):
            self.db.event("WARNING", "send_failure", f"failure {i}")
        for i in range(7):
            self.db.event("INFO", "send_success", f"success {i}")
        self.assertFalse(safety.evaluate().paused)

    def test_runtime_lock_blocks_second_runtime(self):
        path = self.root / "runtime.lock"
        first = RuntimeLock(path)
        first.acquire()
        self.addCleanup(first.release)
        self.assertTrue(path.is_dir())
        with self.assertRaises(RuntimeError):
            RuntimeLock(path).acquire()
        first.release()
        self.assertFalse(path.exists())

    def test_stale_runtime_lock_is_reclaimed(self):
        path = self.root / "runtime.lock"
        path.mkdir()
        (path / "owner.json").write_text(
            json.dumps({"pid": 42424242, "token": "old"}), encoding="utf-8"
        )
        lock = RuntimeLock(path)
        self.addCleanup(lock.release)
        # Do not depend on platform-specific PID probing in this filesystem test.
        with mock.patch("smart_autoposter.runtime_lock._pid_alive", return_value=False):
            lock.acquire()
        self.assertTrue(path.is_dir())
        lock.release()
        self.assertFalse(path.exists())

    def test_old_v30_stale_lock_file_is_reclaimed(self):
        path = self.root / "runtime.lock"
        path.write_text(json.dumps({"pid": 42424242, "token": "old"}), encoding="utf-8")
        lock = RuntimeLock(path)
        self.addCleanup(lock.release)
        with mock.patch("smart_autoposter.runtime_lock._pid_alive", return_value=False):
            lock.acquire()
        self.assertTrue(path.is_dir())
        lock.release()
        self.assertFalse(path.exists())

    def test_uninitialized_fresh_lock_directory_fails_closed(self):
        path = self.root / "runtime.lock"
        path.mkdir()
        with self.assertRaises(RuntimeError):
            RuntimeLock(path).acquire()
        self.assertTrue(path.exists())

    def test_uninitialized_old_lock_directory_is_reclaimed(self):
        path = self.root / "runtime.lock"
        path.mkdir()
        old = time.time() - 120
        os.utime(path, (old, old))
        lock = RuntimeLock(path)
        self.addCleanup(lock.release)
        lock.acquire()
        self.assertTrue(path.is_dir())
        lock.release()
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
