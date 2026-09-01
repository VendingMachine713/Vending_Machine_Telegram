import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.legacy_recovery import recover
from shared.vm_core.relationship_cleanup import plan as cleanup_plan, apply as cleanup_apply
from shared.vm_core.runtime_snapshot import verify


class V14RecoveryRuntimeTests(unittest.TestCase):
    def test_legacy_recovery_uses_pre_v13_snapshot_without_overwriting_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "bots" / "Universal_Search"
            current.mkdir(parents=True)
            (current / "main.py").write_text("from shared.vm_core.search_index import SearchIndex\n", encoding="utf-8")
            (current / "core.py").write_text("VALUE=1\n", encoding="utf-8")
            (current / ".env").write_text("BOT_TOKEN=secret\n", encoding="utf-8")
            (current / "requirements.txt").write_text("# wrapper only\n", encoding="utf-8")
            snap = root / "backups" / "pre_v1_3_ecosystem_20260831_010101" / "bots" / "Universal_Search"
            snap.mkdir(parents=True)
            (snap / "main.py").write_text("from core import VALUE\nprint('legacy bot')\n", encoding="utf-8")
            (snap / "requirements.txt").write_text("python-telegram-bot>=21\npython-dotenv>=1\n", encoding="utf-8")
            result = recover(root, apply=True)
            item = result["bots"][0]
            self.assertTrue(result["ok"], result)
            self.assertTrue(item["eligible"])
            self.assertTrue((current / "legacy_main.py").is_file())
            self.assertIn("SearchIndex", (current / "main.py").read_text())
            req = (current / "requirements.txt").read_text()
            self.assertIn("python-telegram-bot", req)
            self.assertNotIn("secret", json.dumps(result))

    def test_legacy_recovery_rejects_explicit_secret_value_logging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "bots" / "VM_Guard"
            current.mkdir(parents=True)
            snap = root / "backups" / "pre_v1_3_ecosystem_x" / "bots" / "VM_Guard"
            snap.mkdir(parents=True)
            (snap / "main.py").write_text("print(BOT_TOKEN)\n", encoding="utf-8")
            result = recover(root, apply=True)
            item = result["bots"][0]
            self.assertFalse(result["ok"])
            self.assertFalse(item["eligible"])
            self.assertFalse((current / "legacy_main.py").exists())

    def test_legacy_recovery_rejects_hardcoded_token_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "bots" / "Universal_Search"
            current.mkdir(parents=True)
            snap = root / "backups" / "pre_v1_3_ecosystem_x" / "bots" / "Universal_Search"
            snap.mkdir(parents=True)
            (snap / "main.py").write_text(
                'BOT_TOKEN="123:FAKE"\n',
                encoding="utf-8",
            )
            result = recover(root, apply=True)
            item = result["bots"][0]
            self.assertFalse(result["ok"])
            self.assertFalse(item["eligible"])
            self.assertNotIn("123456789:", json.dumps(result))

    def test_relationship_cleanup_archives_older_nested_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outer = root / "bots" / "VM_Relationship_Manager"
            nested = outer / "VM_Relationship_Manager"
            nested.mkdir(parents=True)
            outer.mkdir(parents=True, exist_ok=True)
            exact = {"preflight.py":"x\n", "requirements.txt":"r\n", "START_VM_RELATIONSHIPS.bat":"b\n"}
            for name,text in exact.items():
                (outer/name).write_text(text); (nested/name).write_text(text)
            (outer/"VERSION.txt").write_text("VM Relationship Manager\nBuild: 1.2.0\nUpdated: 2026-08-27\n")
            (nested/"VERSION.txt").write_text("VM Relationship Manager\nBuild: 1.0.2\nUpdated: 2026-08-27\n")
            (outer/"README.md").write_text("new\n"); (nested/"README.md").write_text("old\n")
            (outer/"START_VM_RELATIONSHIPS.ps1").write_text("new\n"); (nested/"START_VM_RELATIONSHIPS.ps1").write_text("old\n")
            (outer/"CHANGELOG.md").write_text("# C\n\n## 1.2.0\nnew\n")
            (nested/"CHANGELOG.md").write_text("# C\n\n## 1.0.2\nold\n")
            p = cleanup_plan(root)
            self.assertTrue(p["safe_to_apply"], p)
            result = cleanup_apply(root)
            self.assertTrue(result["ok"], result)
            self.assertFalse(nested.exists())
            self.assertTrue(Path(result["archive"]).is_file())
            self.assertIn("## 1.0.2", (outer/"CHANGELOG.md").read_text())
            self.assertIn("Build: 1.2.0", (outer/"VERSION.txt").read_text())

    def test_relationship_cleanup_ignores_nested_pycache_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outer = root / "bots" / "VM_Relationship_Manager"
            nested = outer / "VM_Relationship_Manager"
            nested.mkdir(parents=True)
            exact = {"preflight.py":"x\n", "requirements.txt":"r\n", "START_VM_RELATIONSHIPS.bat":"b\n"}
            for name,text in exact.items():
                (outer/name).write_text(text); (nested/name).write_text(text)
            (outer/"VERSION.txt").write_text("VM Relationship Manager\nBuild: 1.2.0\n")
            (nested/"VERSION.txt").write_text("VM Relationship Manager\nBuild: 1.0.2\n")
            (outer/"README.md").write_text("new\n"); (nested/"README.md").write_text("old\n")
            (outer/"START_VM_RELATIONSHIPS.ps1").write_text("new\n"); (nested/"START_VM_RELATIONSHIPS.ps1").write_text("old\n")
            (outer/"CHANGELOG.md").write_text("# C\n\n## 1.2.0\nnew\n")
            (nested/"CHANGELOG.md").write_text("# C\n\n## 1.0.2\nold\n")
            cache = nested/"__pycache__"; cache.mkdir()
            (cache/"preflight.cpython-312.pyc").write_bytes(b"cache")
            p = cleanup_plan(root)
            self.assertTrue(p["safe_to_apply"], p)
            self.assertTrue(p["ignored_disposable_cache_files"])

    def test_runtime_verify_empty_project_is_ok_without_autostart_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/"bots").mkdir()
            result = verify(root)
            self.assertTrue(result["ok"], result)


if __name__ == "__main__":
    unittest.main()
