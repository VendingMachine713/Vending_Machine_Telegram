import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from shared.vm_core.recovery_executor import execute_recovery_plan
from shared.vm_core.recovery_state import RecoveryHistory


class RecoveryExecutionTests(unittest.TestCase):
    def test_history_enforces_cooldown_and_attempt_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = RecoveryHistory(root, base_cooldown_seconds=30, max_attempts=2, window_seconds=300)
            now = datetime(2026, 9, 4, tzinfo=timezone.utc)
            h.record_attempt("A", action="RESTART_SERVICE", success=False, now=now)
            s1 = h.status("A", now=now + timedelta(seconds=10))
            self.assertTrue(s1["cooling_down"])
            h.record_attempt("A", action="RESTART_SERVICE", success=False, now=now + timedelta(seconds=31))
            s2 = h.status("A", now=now + timedelta(seconds=32))
            self.assertTrue(s2["limited"])

    @patch("shared.vm_core.recovery_executor.load_recovery_policy")
    @patch("shared.vm_core.recovery_executor.restart_service")
    def test_executor_is_dry_run_unless_central_apply_policy_is_enabled(self, restart, policy):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy.return_value = {"enabled": False, "apply_safe": False, "max_actions_per_pass": 1}
            restart.return_value = {"ok": True, "dry_run": True}
            plan = {"decisions": [{
                "service": "A", "classification": "AUTO_RECOVER",
                "action": "RESTART_SERVICE", "automatic": True,
            }]}
            result = execute_recovery_plan(plan, root, apply=True)
            self.assertEqual(result["mode"], "DRY_RUN")
            restart.assert_called_once_with("A", root, dry_run=True)

    @patch("shared.vm_core.recovery_executor.verify_service")
    @patch("shared.vm_core.recovery_executor.load_recovery_policy")
    @patch("shared.vm_core.recovery_executor.restart_service")
    def test_apply_mode_verifies_and_records(self, restart, policy, verify):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy.return_value = {"enabled": True, "apply_safe": True, "max_actions_per_pass": 1}
            restart.return_value = {"ok": True}
            verify.return_value = {"verified": True, "reason": "ok"}
            history = MagicMock()
            history.status.return_value = {"limited": False, "cooling_down": False}
            plan = {"decisions": [{
                "service": "A", "classification": "AUTO_RECOVER",
                "action": "RESTART_SERVICE", "automatic": True,
            }]}
            result = execute_recovery_plan(plan, root, apply=True, history=history)
            self.assertEqual(result["mode"], "APPLY_SAFE_RECOVERY")
            self.assertTrue(result["actions"][0]["verification"]["verified"])
            history.record_attempt.assert_called_once()
            history.reset.assert_called_once_with("A")


if __name__ == "__main__":
    unittest.main()
