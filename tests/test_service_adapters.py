import tempfile
import unittest
from pathlib import Path

from shared.vm_core.service_adapters import adapter_registry, adapter_status
from shared.vm_core.manifests import inspect_bot


class ServiceAdapterTests(unittest.TestCase):
    def _bot(self, root: Path, name: str, entrypoint: str, launcher: str) -> Path:
        bot = root / "bots" / name
        bot.mkdir(parents=True)
        (bot / entrypoint).write_text("print('ok')\n", encoding="utf-8")
        (bot / launcher).write_text("# launcher\n", encoding="utf-8")
        return bot

    def test_known_service_adapter_is_ready_with_runnable_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot_dir = self._bot(root, "VM_Guard", "main.py", "START.ps1")
            row = adapter_status(inspect_bot(bot_dir))
            self.assertTrue(row["supported"])
            self.assertEqual(row["adapter_id"], "vm-guard-v1")
            self.assertEqual(row["status"], "READY")
            self.assertIn("entrypoint:main.py", row["evidence"])
            self.assertFalse(row["automatic_execution"] if "automatic_execution" in row else False)

    def test_missing_runtime_file_requires_evidence_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "Universal_Search"
            bot.mkdir(parents=True)
            (bot / "START.ps1").write_text("# launcher\n", encoding="utf-8")
            row = adapter_status(inspect_bot(bot))
            self.assertEqual(row["status"], "EVIDENCE_REQUIRED")
            self.assertIn("entrypoint:main.py", row["missing"])
            self.assertEqual(row["safe_operations"], ["status", "health", "inspect"])

    def test_unknown_service_remains_generic_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = Path(tmp) / "Demo"
            bot.mkdir()
            (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
            row = adapter_status(inspect_bot(bot))
            self.assertFalse(row["supported"])
            self.assertEqual(row["status"], "GENERIC_ONLY")

    def test_registry_keeps_action_authority_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._bot(root, "VM_Guard", "main.py", "START.ps1")
            summary = adapter_registry(root)
            self.assertEqual(summary["supported_count"], 1)
            self.assertEqual(summary["ready_count"], 1)
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
