from pathlib import Path
import tempfile
import unittest

from shared.vm_core.reconciliation import compare_nested_bot


class ReconciliationTests(unittest.TestCase):
    def test_missing_nested_copy_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outer = root / "bots" / "VM_Relationship_Manager"
            outer.mkdir(parents=True)
            (outer / "main.py").write_text("print('ok')\n", encoding="utf-8")
            report = compare_nested_bot(root, "VM_Relationship_Manager")
            self.assertTrue(report["ok"])
            self.assertFalse(report["nested_exists"])
            self.assertTrue(report["safe_to_archive_after_review"])

    def test_exact_duplicate_is_identified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outer = root / "bots" / "VM_Relationship_Manager"
            nested = outer / "VM_Relationship_Manager"
            nested.mkdir(parents=True)
            (outer / "requirements.txt").write_text("x==1\n", encoding="utf-8")
            (nested / "requirements.txt").write_text("x==1\n", encoding="utf-8")
            report = compare_nested_bot(root, "VM_Relationship_Manager")
            self.assertIn("requirements.txt", report["exact_duplicates"])
            self.assertEqual(report["different"], [])

    def test_unique_and_different_files_block_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outer = root / "bots" / "VM_Relationship_Manager"
            nested = outer / "VM_Relationship_Manager"
            nested.mkdir(parents=True)
            (outer / "README.md").write_text("new\n", encoding="utf-8")
            (nested / "README.md").write_text("old\n", encoding="utf-8")
            (nested / "legacy.py").write_text("legacy=True\n", encoding="utf-8")
            report = compare_nested_bot(root, "VM_Relationship_Manager")
            self.assertFalse(report["safe_to_archive_after_review"])
            self.assertIn("legacy.py", report["nested_only"])
            self.assertTrue(any(item["path"] == "README.md" for item in report["different"]))
            self.assertIn("nested_unique_files_require_review", report["blockers"])
            self.assertIn("different_files_require_review", report["blockers"])
            self.assertFalse(report["destructive_action_performed"])


if __name__ == "__main__":
    unittest.main()
