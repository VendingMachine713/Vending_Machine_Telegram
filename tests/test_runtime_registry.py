import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.vm_core.runtime_registry import runtime_registry, write_runtime_registry


class RuntimeRegistryTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        root = Path(tmp)
        bot = root / "bots" / "Demo"
        bot.mkdir(parents=True)
        (bot / "main.py").write_text("x=1\n", encoding="utf-8")
        (bot / "BOT_MANIFEST.json").write_text(json.dumps({
            "schema_version": 3,
            "name": "Demo",
            "version": "1.2.3",
            "classification": "CANONICAL",
            "entrypoint": "main.py",
            "launchers": [],
            "vm_core": {"compatible": True},
            "lifecycle": {"managed_by_vm": True, "auto_start": False, "auto_restart": False},
        }), encoding="utf-8")
        return root

    @patch("shared.vm_core.runtime_registry.service_status")
    def test_runtime_registry_is_safe_and_stable(self, status):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            status.return_value = [{
                "name": "Demo", "runtime_status": "RUNNING", "process_alive": True, "pid": 1234
            }]
            report = runtime_registry(root)
            self.assertEqual(report["service_count"], 1)
            self.assertEqual(report["running_count"], 1)
            self.assertEqual(report["services"][0]["pid"], 1234)
            path = write_runtime_registry(root)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("command_line", text)
            self.assertNotIn("token", text.lower())


if __name__ == "__main__":
    unittest.main()
