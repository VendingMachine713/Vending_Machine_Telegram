import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from shared.vm_core.source_of_truth import (
    bot_version_evidence,
    classify_path,
    create_source_snapshot,
    source_check,
)


def git(root: Path, *args: str):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True, capture_output=True
    )


class SourceOfTruthTests(unittest.TestCase):
    def test_path_policy(self):
        self.assertEqual(classify_path("bots/X/.env"), "sensitive")
        self.assertEqual(classify_path("bots/X/.env.example"), "source")
        self.assertEqual(classify_path("bots/X/a.session"), "sensitive")
        self.assertEqual(classify_path("bots/X/data.sqlite3-wal"), "sensitive")
        self.assertEqual(classify_path("diagnostics/report.txt"), "generated")
        self.assertEqual(classify_path("bots/X/main.py"), "source")

    def _repo(self, root: Path):
        git(root, "init")
        git(root, "config", "user.email", "test@example.com")
        git(root, "config", "user.name", "Test")
        bot = root / "bots" / "VM_Relationship_Manager"
        bot.mkdir(parents=True)
        (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (bot / "VERSION.txt").write_text(
            "VM Relationship Manager\nBuild: 1.2.0\n", encoding="utf-8"
        )
        (bot / "BOT_MANIFEST.json").write_text(
            json.dumps({"version": "1.2.0"}), encoding="utf-8"
        )
        git(root, "add", ".")
        git(root, "commit", "-m", "initial")

    def test_clean_repo_is_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            report = source_check(root)
            self.assertEqual(report["status"], "VERIFIED")
            self.assertEqual(report["blockers"], [])

    def test_duplicate_and_uncommitted_source_are_blockers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            nested = root / "bots" / "VM_Relationship_Manager" / "VM_Relationship_Manager"
            nested.mkdir()
            (nested / "README.md").write_text("legacy", encoding="utf-8")
            (root / "bots" / "VM_Relationship_Manager" / "main.py").write_text(
                "print('changed')\n", encoding="utf-8"
            )
            report = source_check(root)
            self.assertIn("nested_duplicate_bot_folders", report["blockers"])
            self.assertIn("uncommitted_source_changes", report["blockers"])

    def test_tracked_sensitive_file_is_critical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            secret = root / "bots" / "VM_Relationship_Manager" / "account.session"
            secret.write_text("dummy", encoding="utf-8")
            git(root, "add", "-f", str(secret.relative_to(root)))
            git(root, "commit", "-m", "bad fixture")
            report = source_check(root)
            self.assertIn("sensitive_files_tracked", report["blockers"])
            self.assertIn(
                "bots/VM_Relationship_Manager/account.session",
                report["tracked_policy"]["critical"],
            )

    def test_version_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            manifest = root / "bots" / "VM_Relationship_Manager" / "BOT_MANIFEST.json"
            manifest.write_text(json.dumps({"version": "1.1.0"}), encoding="utf-8")
            evidence = bot_version_evidence(root, "VM_Relationship_Manager")
            self.assertFalse(evidence["consistent"])

    def test_snapshot_excludes_sensitive_and_hashes_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            secret = root / "bots" / "VM_Relationship_Manager" / "account.session"
            secret.write_text("dummy", encoding="utf-8")
            git(root, "add", "-f", str(secret.relative_to(root)))
            git(root, "commit", "-m", "fixture sensitive")
            destination = root.parent / (root.name + "_snapshot")
            result = create_source_snapshot(root, destination)
            self.assertTrue(result["ok"])
            self.assertTrue(
                (destination / "bots" / "VM_Relationship_Manager" / "main.py").exists()
            )
            self.assertFalse(
                (destination / "bots" / "VM_Relationship_Manager" / "account.session").exists()
            )
            manifest = json.loads(
                (destination / "SOURCE_SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8")
            )
            self.assertTrue(
                any(item["path"].endswith("account.session") for item in manifest["excluded"])
            )


if __name__ == "__main__":
    unittest.main()
