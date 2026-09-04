import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.autoposter_recovery import recovery_preview


class AutoposterRecoveryGateTests(unittest.TestCase):
    def _root(self):
        root = Path(tempfile.mkdtemp())
        db = root / "bots" / "Smart_Auto_Poster_V2" / "data" / "smart_autoposter.sqlite3"
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE queue(id INTEGER PRIMARY KEY,job_key TEXT,status TEXT,error_kind TEXT)")
        con.execute("CREATE TABLE delivery_attempts(id INTEGER PRIMARY KEY,outcome TEXT)")
        con.commit(); con.close()
        return root, db

    def test_clear_state_is_read_only_review_ready(self):
        root, _ = self._root()
        report = recovery_preview(root)
        self.assertEqual(report["status"], "READY_FOR_REVIEW")
        self.assertFalse(report["safe_to_restart"])

    def test_uncertain_state_blocks_and_does_not_mutate(self):
        root, db = self._root()
        con = sqlite3.connect(db); con.execute("INSERT INTO queue VALUES(1,'job','uncertain','interrupted_send')"); con.commit(); con.close()
        report = recovery_preview(root)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(sqlite3.connect(db).execute("SELECT status FROM queue").fetchone()[0], "uncertain")

    def test_missing_database_fails_closed(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual(recovery_preview(root)["reason"], "database_unavailable")


if __name__ == "__main__":
    unittest.main()
