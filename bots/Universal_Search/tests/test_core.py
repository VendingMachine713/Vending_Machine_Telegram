import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import Store, parse_query, looks_like_ad


class T(unittest.TestCase):
    def test_parse(self):
        q = parse_query("iphone --user @bob --days 7 --limit 5 --ads")
        self.assertEqual(q.text, "iphone")
        self.assertEqual(q.user, "bob")
        self.assertEqual(q.days, 7)
        self.assertEqual(q.limit, 5)
        self.assertTrue(q.ads)

    def test_ad(self):
        self.assertTrue(looks_like_ad("Selling phone $200 available, DM me"))

    def test_store(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "x.db")
            s.upsert(1, "Group", None, 2, "bob", "Bob", 3,
                     "2026-08-29T00:00:00+00:00", "hello iphone", False)
            rows = s.search(parse_query("iphone"), 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source"], "live")

    def test_backfill_upsert_is_idempotent_and_live_wins_source(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "x.db")
            args = (1, "Group", None, 2, "bob", "Bob", 3,
                    "2026-08-29T00:00:00+00:00", "historical iphone", False)
            s.upsert(*args, source="backfill")
            s.upsert(*args, source="backfill")
            self.assertEqual(s.count(), 1)
            self.assertEqual(s.count("backfill"), 1)
            s.upsert(1, "Group", None, 2, "bob", "Bob", 3,
                     "2026-08-29T00:00:00+00:00", "live edit", False, source="live")
            self.assertEqual(s.count(), 1)
            self.assertEqual(s.count("live"), 1)

    def test_schema_migrates_existing_database(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            c = sqlite3.connect(path)
            c.executescript("""
                CREATE TABLE chats(chat_id INTEGER PRIMARY KEY, title TEXT, username TEXT);
                CREATE TABLE senders(sender_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT);
                CREATE TABLE indexed_messages(
                    chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, sender_id INTEGER,
                    date_utc TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
                    has_media INTEGER NOT NULL DEFAULT 0, is_ad INTEGER NOT NULL DEFAULT 0,
                    is_available INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(chat_id,message_id)
                );
            """)
            c.commit()
            c.close()
            s = Store(path)
            with s.conn() as c2:
                cols = {r["name"] for r in c2.execute("PRAGMA table_info(indexed_messages)")}
            self.assertIn("source", cols)

    def test_backfill_progress_accumulates_and_completes(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "x.db")
            s.record_backfill_progress(-100123, "Group", "group", status="running",
                                       oldest_message_id=500, scanned_delta=100)
            s.record_backfill_progress(-100123, "Group", "group", status="complete",
                                       oldest_message_id=400, scanned_delta=75)
            row = s.get_backfill_progress(-100123)
            self.assertEqual(row["status"], "complete")
            self.assertEqual(row["oldest_message_id"], 400)
            self.assertEqual(row["scanned_messages"], 175)
            self.assertTrue(row["completed_utc"])


if __name__ == "__main__":
    unittest.main()
