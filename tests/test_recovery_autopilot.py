from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.vm_core.autopilot import autopilot_once
from shared.vm_core.recovery_policy import load_recovery_policy


class RecoveryAutopilotTests(unittest.TestCase):
    def test_policy_defaults_to_disabled_observe_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = load_recovery_policy(Path(tmp))
            self.assertFalse(policy["enabled"])
            self.assertFalse(policy["apply_safe"])
            self.assertEqual(policy["max_actions_per_pass"], 1)

    def test_policy_bounds_interval_and_action_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "vm_recovery_policy.json").write_text(
                json.dumps({"enabled": True, "apply_safe": True, "interval_seconds": 1, "max_actions_per_pass": 99}),
                encoding="utf-8",
            )
            policy = load_recovery_policy(root)
            self.assertEqual(policy["interval_seconds"], 15)
            self.assertEqual(policy["max_actions_per_pass"], 3)

    @patch("shared.vm_core.autopilot.execute_recovery_plan")
    @patch("shared.vm_core.autopilot.recovery_plan")
    def test_disabled_policy_never_applies_recovery(self, planner, execute):
        planner.return_value = {"summary": {}, "decisions": []}
        execute.return_value = {"actions": []}
        with tempfile.TemporaryDirectory() as tmp:
            result = autopilot_once(Path(tmp))
        self.assertEqual(result["mode"], "OBSERVE_ONLY")
        execute.assert_called_once()
        self.assertFalse(execute.call_args.kwargs["apply"])

    @patch("shared.vm_core.autopilot.execute_recovery_plan")
    @patch("shared.vm_core.autopilot.recovery_plan")
    def test_enabled_policy_can_apply_only_guarded_executor(self, planner, execute):
        planner.return_value = {"summary": {}, "decisions": []}
        execute.return_value = {"actions": []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "vm_recovery_policy.json").write_text(
                json.dumps({"enabled": True, "apply_safe": True, "max_actions_per_pass": 1}),
                encoding="utf-8",
            )
            result = autopilot_once(root)
        self.assertEqual(result["mode"], "ACTIVE_SAFE_RECOVERY")
        self.assertTrue(execute.call_args.kwargs["apply"])
        self.assertEqual(execute.call_args.kwargs["max_actions"], 1)

    @patch("shared.vm_core.autopilot.execute_recovery_plan")
    @patch("shared.vm_core.autopilot.recovery_plan")
    def test_force_observe_overrides_active_policy(self, planner, execute):
        planner.return_value = {"summary": {}, "decisions": []}
        execute.return_value = {"actions": []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "vm_recovery_policy.json").write_text(
                json.dumps({"enabled": True, "apply_safe": True}), encoding="utf-8"
            )
            result = autopilot_once(root, force_observe=True)
        self.assertEqual(result["mode"], "OBSERVE_ONLY")
        self.assertFalse(execute.call_args.kwargs["apply"])


if __name__ == "__main__":
    unittest.main()
