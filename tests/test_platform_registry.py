import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.platform_registry import describe_services, service_registry, write_service_registry


class PlatformRegistryTests(unittest.TestCase):
    def test_manifest_metadata_becomes_stable_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "Demo"
            bot.mkdir(parents=True)
            (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (bot / "BOT_MANIFEST.json").write_text(json.dumps({
                "schema_version": 3,
                "name": "Demo",
                "version": "1.2.3",
                "classification": "CANONICAL",
                "entrypoint": "main.py",
                "entrypoint_confidence": "high",
                "launchers": [],
                "capabilities": ["search", "status", "search"],
                "runtime_requirements": {"env": ["BOT_TOKEN"], "optional_env": ["API_ID"]},
                "vm_core": {"compatible": True},
                "lifecycle": {"managed_by_vm": True, "auto_start": False, "auto_restart": False},
            }), encoding="utf-8")
            item = describe_services(root)[0]
            self.assertEqual(item.name, "Demo")
            self.assertEqual(item.version, "1.2.3")
            self.assertEqual(item.capabilities, ["search", "status"])
            self.assertEqual(item.runtime_required_env, ["BOT_TOKEN"])
            self.assertTrue(item.managed_by_vm)

    def test_registry_write_contains_no_environment_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "Demo"
            bot.mkdir(parents=True)
            (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (bot / "BOT_MANIFEST.json").write_text(json.dumps({
                "schema_version": 3,
                "name": "Demo",
                "version": "1.0.0",
                "classification": "CANONICAL",
                "entrypoint": "main.py",
                "launchers": [],
                "runtime_requirements": {"env": ["SUPER_SECRET"]},
                "vm_core": {"compatible": True},
                "lifecycle": {"managed_by_vm": True, "auto_start": False, "auto_restart": False},
            }), encoding="utf-8")
            path = write_service_registry(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["service_count"], 1)
            self.assertIn("SUPER_SECRET", path.read_text(encoding="utf-8"))
            self.assertNotIn("secret-value", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
