import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.vm_core.admin_exceptions import admin_exceptions, format_admin_exceptions
from shared.vm_core.incident_runtime import sync_recovery_incidents


class IncidentExceptionTests(unittest.TestCase):
    @patch("shared.vm_core.incident_runtime.recovery_plan")
    def test_recovery_incident_opens_and_resolves(self, plan):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan.return_value = {"decisions": [{
                "service": "Demo", "classification": "BLOCKED",
                "failure_class": "SESSION", "action": "INVESTIGATE", "reason": "blocked"
            }]}
            first = sync_recovery_incidents(root)
            self.assertEqual(first["open_or_refreshed"], 1)
            self.assertEqual(len(first["open_incidents"]), 1)

            plan.return_value = {"decisions": [{
                "service": "Demo", "classification": "HEALTHY",
                "failure_class": "NONE", "action": "NONE", "reason": "ok"
            }]}
            second = sync_recovery_incidents(root)
            self.assertEqual(second["resolved"], 1)

    @patch("shared.vm_core.admin_exceptions.sync_recovery_incidents")
    @patch("shared.vm_core.admin_exceptions.recovery_plan")
    def test_quiet_admin_surface(self, plan, sync):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync.return_value = {"open_or_refreshed": 0, "resolved": 0, "open_incidents": []}
            plan.return_value = {"decisions": []}
            report = admin_exceptions(root)
            self.assertTrue(report["quiet"])
            self.assertIn("No material", format_admin_exceptions(report))


if __name__ == "__main__":
    unittest.main()
