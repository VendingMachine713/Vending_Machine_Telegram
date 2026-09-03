from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from shared.vm_core.recovery import classify_service, execute_recovery_plan, format_recovery_plan, recovery_plan
from shared.vm_core.recovery_cli import main as recovery_cli


class RecoveryIntelligenceTests(unittest.TestCase):
    def test_alive_service_is_healthy_and_never_restarted(self):
        d = classify_service(
            {"name": "VM_Guard", "process_alive": True, "runtime_status": "RUNNING"},
            {"auto_start": True, "auto_restart": True},
        )
        self.assertEqual(d.classification, "HEALTHY")
        self.assertEqual(d.action, "NONE")
        self.assertFalse(d.automatic)

    def test_manifest_authorized_stopped_service_is_safe_candidate(self):
        d = classify_service(
            {"name": "Universal_Search", "process_alive": False, "runtime_status": "STOPPED"},
            {"auto_start": False, "auto_restart": True},
        )
        self.assertEqual(d.classification, "SAFE_RECOVERY")
        self.assertEqual(d.action, "RESTART_SERVICE")
        self.assertTrue(d.automatic)

    def test_auth_or_delivery_ambiguity_blocks_automatic_recovery(self):
        d = classify_service(
            {
                "name": "Smart_Auto_Poster_V2",
                "process_alive": False,
                "runtime_status": "FAILED",
                "last_error": "Telegram session auth failed while delivery uncertain",
            },
            {"auto_start": True, "auto_restart": True},
        )
        self.assertEqual(d.classification, "BLOCKED")
        self.assertEqual(d.action, "INVESTIGATE")
        self.assertFalse(d.automatic)
        self.assertTrue(d.requires_operator)

    @patch("shared.vm_core.recovery._manifest_policy")
    @patch("shared.vm_core.recovery.discover_bots")
    @patch("shared.vm_core.recovery.service_status")
    def test_plan_is_read_only_and_counts_safe_candidates(self, status, discover, policy):
        status.return_value = [
            {"name": "A", "process_alive": True, "runtime_status": "RUNNING"},
            {"name": "B", "process_alive": False, "runtime_status": "STOPPED"},
        ]
        discover.return_value = [
            SimpleNamespace(folder="A", classification="CANONICAL", path="/tmp/A"),
            SimpleNamespace(folder="B", classification="CANONICAL", path="/tmp/B"),
        ]
        policy.side_effect = [
            {"auto_start": True, "auto_restart": True},
            {"auto_start": False, "auto_restart": True},
        ]
        plan = recovery_plan(Path("/tmp/project"))
        self.assertEqual(plan["mode"], "READ_ONLY_PLAN")
        self.assertEqual(plan["summary"]["healthy"], 1)
        self.assertEqual(plan["summary"]["automatic_candidates"], 1)
        self.assertFalse(plan["safety"]["mutations_performed"])
        self.assertFalse(plan["safety"]["uncertain_delivery_auto_retry"])

    @patch("shared.vm_core.recovery.restart_service")
    def test_executor_is_dry_run_by_default_and_caps_actions(self, restart):
        restart.return_value = {"ok": True, "dry_run": True}
        plan = {
            "decisions": [
                {"service": "A", "classification": "SAFE_RECOVERY", "action": "RESTART_SERVICE", "automatic": True},
                {"service": "B", "classification": "SAFE_RECOVERY", "action": "RESTART_SERVICE", "automatic": True},
            ]
        }
        result = execute_recovery_plan(plan, Path("/tmp/project"))
        self.assertEqual(result["mode"], "DRY_RUN")
        self.assertEqual(result["candidate_count"], 1)
        restart.assert_called_once_with("A", Path("/tmp/project"), dry_run=True)
        self.assertFalse(result["safety"]["queue_or_delivery_retry_performed"])
        self.assertEqual(result["verification_failures"], 0)

    @patch("shared.vm_core.recovery.verify_service_recovered")
    @patch("shared.vm_core.recovery.restart_service")
    def test_apply_mode_verifies_recovery_and_records_success(self, restart, verify):
        restart.return_value = {"ok": True}
        verify.return_value = {"verified": True, "process_alive": True, "runtime_status": "RUNNING"}
        history = MagicMock()
        history.status.return_value = {"limited": False, "cooling_down": False}
        plan = {"decisions": [{"service": "A", "classification": "SAFE_RECOVERY", "action": "RESTART_SERVICE", "automatic": True}]}
        result = execute_recovery_plan(plan, Path("/tmp/project"), apply=True, history=history)
        self.assertFalse(result["operator_escalation_required"])
        self.assertTrue(result["actions"][0]["verification"]["verified"])
        history.record_attempt.assert_called_once_with("A", action="RESTART_SERVICE", success=True)

    @patch("shared.vm_core.recovery.verify_service_recovered")
    @patch("shared.vm_core.recovery.restart_service")
    def test_failed_verification_requires_operator_escalation(self, restart, verify):
        restart.return_value = {"ok": True}
        verify.return_value = {"verified": False, "process_alive": False, "runtime_status": "STOPPED"}
        history = MagicMock()
        history.status.return_value = {"limited": False, "cooling_down": False}
        plan = {"decisions": [{"service": "A", "classification": "SAFE_RECOVERY", "action": "RESTART_SERVICE", "automatic": True}]}
        result = execute_recovery_plan(plan, Path("/tmp/project"), apply=True, history=history)
        self.assertEqual(result["verification_failures"], 1)
        self.assertTrue(result["operator_escalation_required"])
        history.record_attempt.assert_called_once_with("A", action="RESTART_SERVICE", success=False)

    @patch("shared.vm_core.recovery.restart_service")
    @patch("shared.vm_core.recovery.start_service")
    def test_executor_never_runs_blocked_or_review_actions(self, start, restart):
        plan = {
            "decisions": [
                {"service": "A", "classification": "BLOCKED", "action": "RESTART_SERVICE", "automatic": True},
                {"service": "B", "classification": "REVIEW", "action": "START_SERVICE", "automatic": True},
            ]
        }
        result = execute_recovery_plan(plan, Path("/tmp/project"), apply=True, max_actions=5)
        self.assertEqual(result["candidate_count"], 0)
        start.assert_not_called()
        restart.assert_not_called()

    def test_formatter_exposes_safety_boundary(self):
        text = format_recovery_plan({
            "mode": "READ_ONLY_PLAN",
            "summary": {"services": 1, "healthy": 0, "automatic_candidates": 1, "operator_attention": 0, "blocked": 0},
            "decisions": [{"classification": "SAFE_RECOVERY", "service": "X", "action": "RESTART_SERVICE", "reason": "policy permits"}],
        })
        self.assertIn("VM RECOVERY INTELLIGENCE", text)
        self.assertIn("planning only", text)
        self.assertIn("RESTART_SERVICE", text)

    @patch("shared.vm_core.recovery_cli.recovery_plan")
    def test_cli_json_is_machine_readable(self, planner):
        planner.return_value = {"mode": "READ_ONLY_PLAN", "summary": {}, "decisions": [], "safety": {}}
        output = io.StringIO()
        with redirect_stdout(output):
            rc = recovery_cli(["--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "READ_ONLY_PLAN")


if __name__ == "__main__":
    unittest.main()
