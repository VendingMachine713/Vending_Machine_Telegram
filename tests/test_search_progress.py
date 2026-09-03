from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.search_progress import universal_search_progress


class UniversalSearchProgressTests(unittest.TestCase):
    def _root_with_db(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        data = root / "bots" / "Universal_Search" / "data"
        data.mkdir(parents=True)
        db = data / "universal_search.db"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE indexed_messages(chat_id INTEGER,message_id INTEGER,PRIMARY KEY(chat_id,message_id));
            CREATE TABLE saved_searches(id INTEGER PRIMARY KEY,name TEXT,enabled INTEGER);
            CREATE TABLE alert_queue(
              id INTEGER PRIMARY KEY,
              watch_id INTEGER,
              chat_id INTEGER,
              message_id INTEGER,
              status TEXT,
              attempts INTEGER,
              due_utc TEXT,
              last_error TEXT
            );
            INSERT INTO indexed_messages VALUES(1,1);
            INSERT INTO indexed_messages VALUES(1,2);
            INSERT INTO saved_searches VALUES(7,'iphone-watch',1);
            INSERT INTO alert_queue VALUES(1,7,1,1,'sent',1,'2026-09-03T00:00:00Z',NULL);
            INSERT INTO alert_queue VALUES(2,7,1,2,'pending',0,'2026-09-03T00:10:00Z',NULL);
            """
        )
        con.commit(); con.close()
        return tmp, root, db

    def test_alert_queue_maps_to_three_tier_progress(self):
        tmp, root, _ = self._root_with_db(); self.addCleanup(tmp.cleanup)
        snapshot = universal_search_progress(root)
        self.assertEqual(snapshot["headline"], "UNIVERSAL SEARCH - UNIVERSAL PROGRESS")
        self.assertEqual(snapshot["overall"]["percent"], 50)
        self.assertEqual(snapshot["overall"]["status"], "RUNNING")
        self.assertEqual(snapshot["group"]["label"], "iphone-watch")
        self.assertEqual(snapshot["task"]["label"], "Alert #2")
        self.assertEqual(snapshot["metrics"]["indexed_messages"], 2)
        self.assertEqual(snapshot["metrics"]["enabled_watches"], 1)

    def test_failed_alert_sets_attention_and_recovery(self):
        tmp, root, db = self._root_with_db(); self.addCleanup(tmp.cleanup)
        con = sqlite3.connect(db)
        con.execute("UPDATE alert_queue SET status='failed',last_error='blocked' WHERE id=2")
        con.commit(); con.close()
        snapshot = universal_search_progress(root)
        self.assertEqual(snapshot["overall"]["status"], "ATTENTION")
        self.assertEqual(snapshot["overall"]["percent"], 100)
        self.assertTrue(any("terminally failed" in item for item in snapshot["recovery_messages"]))

    def test_empty_alert_queue_reports_index_ready(self):
        tmp, root, db = self._root_with_db(); self.addCleanup(tmp.cleanup)
        con = sqlite3.connect(db); con.execute("DELETE FROM alert_queue"); con.commit(); con.close()
        snapshot = universal_search_progress(root)
        self.assertEqual(snapshot["overall"]["status"], "READY")
        self.assertEqual(snapshot["overall"]["percent"], 100)
        self.assertIsNone(snapshot["task"])

    def test_missing_database_degrades_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = universal_search_progress(Path(tmp))
        self.assertEqual(snapshot["overall"]["status"], "DEGRADED")
        self.assertTrue(snapshot["recovery_messages"])


if __name__ == "__main__":
    unittest.main()
