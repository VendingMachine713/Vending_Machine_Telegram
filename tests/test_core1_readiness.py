import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.vm_core.core1_readiness import core1_readiness


class Core1ReadinessTests(unittest.TestCase):
    @patch("shared.vm_core.runtime_registry.service_status")
    def test_clean_platform_reports_ready(self, status):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "Demo"
            bot.mkdir(parents=True)
            (bot / "main.py").write_text(
                "from shared.vm_core.service_context import service_context\n"
                "from shared.vm_core.publisher import BotEventPublisher\n",
                encoding="utf-8",
            )
            (bot / "BOT_MANIFEST.json").write_text(json.dumps({
                "schema_version": 3,
                "name": "Demo",
                "version": "1.0.0",
                "classification": "CANONICAL",
                "entrypoint": "main.py",
                "launchers": [],
                "runtime_requirements": {"env": ["BOT_TOKEN"]},
                "vm_core": {"compatible": True},
                "lifecycle": {"managed_by_vm": True, "auto_start": False, "auto_restart": False},
            }), encoding="utf-8")
            (root / "VM_PROJECT.json").write_text(json.dumps({
                "project": "Test", "canonical_bot_folders": ["Demo"]
            }), encoding="utf-8")
            status.return_value = [{
                "name": "Demo", "runtime_status": "STOPPED", "process_alive": False, "pid": None
            }]
            report = core1_readiness(root)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["service_count"], 1)
            self.assertTrue(report["integration_adoption"][0]["service_context"])
            self.assertTrue(report["integration_adoption"][0]["event_publisher"])


if __name__ == "__main__":
    unittest.main()
