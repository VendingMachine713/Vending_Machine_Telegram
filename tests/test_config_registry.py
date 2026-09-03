import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.config_registry import configuration_registry, write_configuration_registry


class ConfigRegistryTests(unittest.TestCase):
    def test_registry_contains_key_names_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "Demo"
            bot.mkdir(parents=True)
            (bot / "main.py").write_text("x=1\n", encoding="utf-8")
            (bot / "BOT_MANIFEST.json").write_text(json.dumps({
                "schema_version": 3,
                "name": "Demo",
                "version": "1.0.0",
                "classification": "CANONICAL",
                "entrypoint": "main.py",
                "launchers": [],
                "runtime_requirements": {"env": ["BOT_TOKEN"], "optional_env": ["API_ID"]},
                "vm_core": {"compatible": True},
                "lifecycle": {"managed_by_vm": True, "auto_start": False, "auto_restart": False},
            }), encoding="utf-8")
            report = configuration_registry(root)
            self.assertEqual(report["required_key_count"], 1)
            self.assertEqual(report["services"][0]["required_keys"], ["BOT_TOKEN"])
            path = write_configuration_registry(root)
            text = path.read_text(encoding="utf-8")
            self.assertIn("BOT_TOKEN", text)
            self.assertNotIn("secret-value", text)


if __name__ == "__main__":
    unittest.main()
