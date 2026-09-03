from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.autoposter_progress import smart_auto_poster_progress


class AutoPosterProgressTests(unittest.TestCase):
    def _root_with_db(self) -> tuple[tempfile.TemporaryDirectory, Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        bot = root / "bots" / "Smart_Auto_Poster_V2"
        data = bot / "data"
        data.mkdir(parents=True)
        db = data / "smart_autoposter.sqlite3"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE destinations(group_id INTEGER PRIMARY KEY, group_name TEXT);
            CREATE TABLE queue(
                id INTEGER PRIMARY KEY,
                campaign_id INTEGER,
                group_id INTEGER,
                account_key TEXT,
                status TEXT,
                error_kind TEXT,
                last_error TEXT,
                updated_at TEXT
            );
            INSERT INTO destinations VALUES(1001, 'Test Group A');
            INSERT INTO destinations VALUES(1002, 'Test Group B');
            INSERT INTO queue VALUES(1, 7, 1001, 'primary', 'sent', NULL, NULL, '2026-09-03T00:00:00Z');
            INSERT INTO queue VALUES(2, 7, 1002, 'secondary', 'pending', NULL, NULL, '2026-09-03T00:01:00Z');
            """
        )
        con.commit()
        con.close()
        return tmp, root, db

    def test_maps_queue_into_three_tier_progress(self):
        tmp, root, _ = self._root_with_db()
        self.addCleanup(tmp.cleanup)
        snapshot = smart_auto_poster_progress(root)
        self.assertEqual(snapshot["headline"], "SMART AUTO POSTER - UNIVERSAL PROGRESS")
        self.assertEqual(snapshot["overall"]["current"], 1)
        self.assertEqual(snapshot["overall"]["total"], 2)
        self.assertEqual(snapshot["overall"]["percent"], 50)
        self.assertEqual(snapshot["group"]["label"], "Test Group B")
        self.assertEqual(snapshot["task"]["label"], "Queue job #2")

    def test_uncertain_never_claims_completion_and_emits_recovery(self):
        tmp, root, db = self._root_with_db()
        self.addCleanup(tmp.cleanup)
        con = sqlite3.connect(db)
        con.execute("UPDATE queue SET status='uncertain', error_kind='timeout' WHERE id=2")
        con.commit()
        con.close()
        snapshot = smart_auto_poster_progress(root)
        self.assertEqual(snapshot["overall"]["status"], "ATTENTION")
        self.assertEqual(snapshot["overall"]["percent"], 50)
        self.assertTrue(any("auto-retry blocked" in item for item in snapshot["recovery_messages"]))
        self.assertEqual(snapshot["events"][0]["level"], "WARN")

    def test_missing_database_is_safe_and_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = smart_auto_poster_progress(Path(tmp))
        self.assertEqual(snapshot["overall"]["status"], "DEGRADED")
        self.assertTrue(snapshot["recovery_messages"])


if __name__ == "__main__":
    unittest.main()
