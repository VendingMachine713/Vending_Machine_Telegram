import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.foundation import foundation_report, validate_bot_contract


class FoundationContractTests(unittest.TestCase):
    def _manifest(self, name: str) -> dict:
        return {
            "schema_version": 3,
            "name": name,
            "version": "1.0.0",
            "classification": "CANONICAL",
            "entrypoint": "main.py",
            "launchers": [],
            "vm_core": {"compatible": True, "minimum_version": "1.1.0"},
            "lifecycle": {
                "managed_by_vm": True,
                "auto_start": False,
                "auto_restart": False,
            },
        }

    def test_valid_manifest_satisfies_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = Path(tmp) / "Demo"
            bot.mkdir()
            (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (bot / "BOT_MANIFEST.json").write_text(
                json.dumps(self._manifest("Demo")), encoding="utf-8"
            )
            self.assertEqual(validate_bot_contract(bot), [])

    def test_name_mismatch_and_missing_entrypoint_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = Path(tmp) / "Demo"
            bot.mkdir()
            manifest = self._manifest("Wrong")
            (bot / "BOT_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
            findings = validate_bot_contract(bot)
            codes = {item.code for item in findings if item.severity == "ERROR"}
            self.assertIn("MANIFEST_NAME_MISMATCH", codes)
            self.assertIn("ENTRYPOINT_MISSING", codes)

    def test_foundation_report_checks_project_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "Demo"
            bot.mkdir(parents=True)
            (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (bot / "BOT_MANIFEST.json").write_text(
                json.dumps(self._manifest("Demo")), encoding="utf-8"
            )
            (root / "VM_PROJECT.json").write_text(
                json.dumps({"project": "Test", "canonical_bot_folders": ["Demo"]}),
                encoding="utf-8",
            )
            report = foundation_report(root)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["summary"]["ERROR"], 0)


if __name__ == "__main__":
    unittest.main()
