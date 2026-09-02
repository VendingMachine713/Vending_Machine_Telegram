import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import Store, build_fts_query, looks_like_ad, parse_query


class T(unittest.TestCase):
    def make_store(self, directory):
        return Store(Path(directory) / "x.db")

    def seed(self, store):
        store.upsert(
            -1001, "Phones", "phones", 2, "bob", "Bob", 1,
            "2026-08-29T00:00:00+00:00", "iphone 15 pro available $900 dm me", False,
        )
        store.upsert(
            -1001, "Phones", "phones", 3, "sam", "Sam", 2,
            "2026-08-30T00:00:00+00:00", "samsung galaxy phone case", True,
        )
        store.upsert(
            -1001, "Phones", "phones", 2, "bob", "Bob", 3,
            "2026-08-31T00:00:00+00:00", "iphone case for 15 pro", True,
        )

    def test_parse(self):
        q = parse_query("iphone --user @bob --days 7 --limit 5 --ads")
        self.assertEqual(q.text, "iphone")
        self.assertEqual(q.user, "bob")
        self.assertEqual(q.days, 7)
        self.assertEqual(q.limit, 5)
        self.assertTrue(q.ads)

    def test_parse_advanced_query(self):
        q = parse_query(
            'iphone OR samsung "pro max" -case --media --sort newest --page 3 --limit 4'
        )
        self.assertEqual(q.terms, ("iphone", "samsung"))
        self.assertEqual(q.exact_phrases, ("pro max",))
        self.assertEqual(q.exclude_terms, ("case",))
        self.assertTrue(q.use_or)
        self.assertTrue(q.media)
        self.assertEqual(q.sort, "newest")
        self.assertEqual(q.page, 3)
        self.assertEqual(q.offset, 8)
        self.assertIn("NOT", build_fts_query(q))

    def test_invalid_sort_falls_back_to_relevant(self):
        q = parse_query("iphone --sort random")
        self.assertEqual(q.sort, "relevant")

    def test_ad(self):
        self.assertTrue(looks_like_ad("Selling phone $200 available, DM me"))

    def test_store(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
            s.upsert(1, "Group", None, 2, "bob", "Bob", 3,
                     "2026-08-29T00:00:00+00:00", "hello iphone", False)
            rows, has_more = s.search(parse_query("iphone"), 1)
            self.assertEqual(len(rows), 1)
            self.assertFalse(has_more)
            self.assertEqual(rows[0]["source"], "live")

    def test_exact_phrase_and_exclusion(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
            self.seed(s)
            rows, _ = s.search(parse_query('"iphone 15 pro" -case'), -1001)
            self.assertEqual([r["message_id"] for r in rows], [1])

    def test_or_query(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
            self.seed(s)
            rows, _ = s.search(parse_query("iphone OR samsung --limit 10"), -1001)
            self.assertEqual({r["message_id"] for r in rows}, {1, 2, 3})

    def test_media_filter(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
            self.seed(s)
            rows, _ = s.search(parse_query("case --media"), -1001)
            self.assertEqual({r["message_id"] for r in rows}, {2, 3})

    def test_sort_newest_and_oldest(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
            self.seed(s)
            newest, _ = s.search(parse_query("phone OR iphone --sort newest"), -1001)
            oldest, _ = s.search(parse_query("phone OR iphone --sort oldest"), -1001)
            self.assertEqual(newest[0]["message_id"], 3)
            self.assertEqual(oldest[0]["message_id"], 1)

    def test_pagination(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
            self.seed(s)
            page1, more1 = s.search(parse_query("iphone --limit 1 --page 1"), -1001)
            page2, more2 = s.search(parse_query("iphone --limit 1 --page 2"), -1001)
            self.assertEqual(len(page1), 1)
            self.assertTrue(more1)
            self.assertEqual(len(page2), 1)
            self.assertFalse(more2)
            self.assertNotEqual(page1[0]["message_id"], page2[0]["message_id"])

    def test_fts_stays_in_sync_after_edit(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
            s.upsert(1, "Group", None, 2, "bob", "Bob", 3,
                     "2026-08-29T00:00:00+00:00", "oldword", False)
            s.upsert(1, "Group", None, 2, "bob", "Bob", 3,
                     "2026-08-29T00:00:00+00:00", "newword", False)
            old_rows, _ = s.search(parse_query("oldword"), 1)
            new_rows, _ = s.search(parse_query("newword"), 1)
            self.assertEqual(old_rows, [])
            self.assertEqual(len(new_rows), 1)

    def test_like_fallback_keeps_advanced_filters(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
            self.seed(s)
            s.fts_enabled = False
            rows, _ = s.search(parse_query("iphone -case"), -1001)
            self.assertEqual([r["message_id"] for r in rows], [1])

    def test_recent_searches_and_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
            s.record_search(10, "iphone")
            s.record_search(10, "samsung")
            recent = s.recent_searches(10)
            self.assertEqual([r["query"] for r in recent], ["samsung", "iphone"])
            s.save_search_session("abc", 10, -1001, "iphone", False, False)
            session = s.get_search_session("abc")
            self.assertEqual(session["user_id"], 10)
            self.assertEqual(session["chat_scope"], -1001)

    def test_backfill_upsert_is_idempotent_and_live_wins_source(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
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

    def test_schema_migrates_existing_database_and_backfills_fts(self):
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
                INSERT INTO indexed_messages(chat_id,message_id,date_utc,text)
                VALUES(1,1,'2026-08-29T00:00:00+00:00','legacy searchable text');
            """)
            c.commit()
            c.close()
            s = Store(path)
            with s.conn() as c2:
                cols = {r["name"] for r in c2.execute("PRAGMA table_info(indexed_messages)")}
            self.assertIn("source", cols)
            rows, _ = s.search(parse_query("searchable"), 1)
            self.assertEqual(len(rows), 1)

    def test_backfill_progress_accumulates_and_completes(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make_store(d)
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
