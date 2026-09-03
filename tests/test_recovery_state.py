from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.vm_core.recovery_state import RecoveryHistory


class RecoveryHistoryTests(unittest.TestCase):
    def test_first_attempt_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = RecoveryHistory(Path(tmp), base_cooldown_seconds=60, max_attempts=3, window_seconds=3600)
            state = history.status("VM_Guard", datetime(2026, 9, 3, tzinfo=timezone.utc))
            self.assertEqual(state["attempts"], 0)
            self.assertFalse(state["cooling_down"])
            self.assertFalse(state["limited"])

    def test_recorded_attempt_enforces_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = RecoveryHistory(Path(tmp), base_cooldown_seconds=60, max_attempts=3, window_seconds=3600)
            now = datetime(2026, 9, 3, tzinfo=timezone.utc)
            history.record_attempt("VM_Guard", action="RESTART_SERVICE", success=True, now=now)
            state = history.status("VM_Guard", now + timedelta(seconds=30))
            self.assertEqual(state["attempts"], 1)
            self.assertTrue(state["cooling_down"])
            self.assertFalse(state["limited"])

    def test_backoff_increases_after_repeated_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = RecoveryHistory(Path(tmp), base_cooldown_seconds=60, max_attempts=4, window_seconds=3600)
            t0 = datetime(2026, 9, 3, tzinfo=timezone.utc)
            history.record_attempt("X", action="RESTART_SERVICE", now=t0)
            history.record_attempt("X", action="RESTART_SERVICE", now=t0 + timedelta(seconds=61))
            state = history.status("X", t0 + timedelta(seconds=62))
            self.assertEqual(state["attempts"], 2)
            self.assertEqual(state["cooldown_seconds"], 120)
            self.assertTrue(state["cooling_down"])

    def test_attempt_limit_blocks_restart_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = RecoveryHistory(Path(tmp), base_cooldown_seconds=30, max_attempts=2, window_seconds=3600)
            t0 = datetime(2026, 9, 3, tzinfo=timezone.utc)
            history.record_attempt("X", action="RESTART_SERVICE", now=t0)
            history.record_attempt("X", action="RESTART_SERVICE", now=t0 + timedelta(seconds=31))
            state = history.status("X", t0 + timedelta(seconds=32))
            self.assertTrue(state["limited"])

    def test_window_expiry_resets_attempt_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = RecoveryHistory(Path(tmp), base_cooldown_seconds=30, max_attempts=2, window_seconds=120)
            t0 = datetime(2026, 9, 3, tzinfo=timezone.utc)
            history.record_attempt("X", action="RESTART_SERVICE", now=t0)
            state = history.status("X", t0 + timedelta(seconds=121))
            self.assertEqual(state["attempts"], 0)
            self.assertFalse(state["limited"])


if __name__ == "__main__":
    unittest.main()
