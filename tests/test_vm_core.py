from pathlib import Path
import json
import tempfile
import unittest

from shared.vm_core.manifests import discover_bots, create_missing_bot_manifests
from shared.vm_core.paths import ensure_platform_dirs
from shared.vm_core.inspect import build_structure_report


class VMCoreTests(unittest.TestCase):
    def test_platform_directories_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ensure_platform_dirs(root)
            ensure_platform_dirs(root)
            self.assertTrue((root / "diagnostics").is_dir())
            self.assertTrue((root / "state").is_dir())

    def test_root_entrypoint_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "Example_Bot"
            bot.mkdir(parents=True)
            (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
            found = discover_bots(root)
            self.assertEqual(found[0].entrypoint, "main.py")
            self.assertEqual(found[0].entrypoint_confidence, "high")

    def test_launcher_entrypoint_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "Launcher_Bot"
            (bot / "src").mkdir(parents=True)
            (bot / "src" / "worker.py").write_text("print('ok')\n", encoding="utf-8")
            (bot / "START.bat").write_text('@echo off\npy src\\worker.py\n', encoding="utf-8")
            found = discover_bots(root)
            self.assertEqual(found[0].entrypoint, "src/worker.py")
            self.assertEqual(found[0].entrypoint_confidence, "high")

    def test_safe_structure_redacts_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "Example_Bot"
            bot.mkdir(parents=True)
            (bot / ".env").write_text("SECRET=do-not-read\n", encoding="utf-8")
            (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
            report = build_structure_report(root)
            tree = report["bots"][0]["tree"]
            self.assertIn(".env [REDACTED FILE]", tree)
            self.assertFalse(any("do-not-read" in x for x in tree))

    def test_manifest_creation_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bot = root / "bots" / "Example_Bot"
            bot.mkdir(parents=True)
            (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")

            preview = create_missing_bot_manifests(root, write=False)
            self.assertEqual(preview[0]["action"], "would_create")
            self.assertFalse((bot / "BOT_MANIFEST.json").exists())

            created = create_missing_bot_manifests(root, write=True)
            self.assertEqual(created[0]["action"], "created")

            manifest_path = bot / "BOT_MANIFEST.json"
            original = json.loads(manifest_path.read_text(encoding="utf-8"))
            original["sentinel"] = "preserve"
            manifest_path.write_text(json.dumps(original), encoding="utf-8")

            preserved = create_missing_bot_manifests(root, write=True)
            self.assertEqual(preserved[0]["action"], "preserved")
            after = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(after["sentinel"], "preserve")


if __name__ == "__main__":
    unittest.main()
