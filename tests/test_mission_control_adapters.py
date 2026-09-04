import tempfile
import unittest
from pathlib import Path

from shared.vm_core.mission_control import mission_control


class MissionControlAdapterTests(unittest.TestCase):
    def test_adapter_surface_is_additive_and_advisory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "VM_Guard"
            bot.mkdir(parents=True)
            (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (bot / "START.ps1").write_text("# launcher\n", encoding="utf-8")

            summary = mission_control(root)
            self.assertEqual(summary["contract_version"], 4)
            self.assertGreaterEqual(summary["platform"]["revision"], 1)
            self.assertIn("adapters", summary["platform"])
            self.assertEqual(summary["headline"]["adapter_supported_services"], 1)
            self.assertEqual(summary["headline"]["adapter_ready_services"], 1)
            self.assertFalse(summary["automatic_acceptance"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])
            self.assertFalse(summary["platform"]["adapters"]["automatic_execution"])


if __name__ == "__main__":
    unittest.main()
