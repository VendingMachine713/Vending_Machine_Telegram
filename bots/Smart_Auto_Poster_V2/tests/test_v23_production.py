import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from smart_autoposter.content_library import import_content_inbox
from smart_autoposter.core import (
    add_campaign_content, campaign_preview, clone_campaign, create_campaign, create_content,
    enqueue_campaign, record_content_sent, refresh_system_tags,
)
from smart_autoposter.db import Database, utcnow
from smart_autoposter.scheduler import configure_interval, simulate_schedules


class V23ProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_cwd = Path.cwd()
        import os
        os.chdir(self.root)
        self.db = Database(self.root / "data" / "test.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute("""INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at)
                           VALUES(-1001,'Main',1,1,'primary','text',1,0,?)""", (now,))
            con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(-1001,'main')")
        create_content(self.db, "ad_a", "A", [])
        create_content(self.db, "ad_b", "B", [])
        create_campaign(self.db, "camp", "Campaign", "ad_a", tags="main", rotation_mode="sequential")
        add_campaign_content(self.db, "camp", "ad_b", position=1)
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active' WHERE campaign_id='camp'")

    def tearDown(self):
        import os
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_schema_v4_tables_and_columns(self):
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "7")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("campaign_content", tables)
            self.assertIn("content_usage", tables)
            qcols = {r[1] for r in con.execute("PRAGMA table_info(queue)")}
            self.assertIn("content_id", qcols)

    def test_sequential_rotation_uses_different_variant(self):
        a = enqueue_campaign(self.db, "camp", run_key="one")
        b = enqueue_campaign(self.db, "camp", run_key="two")
        self.assertEqual(a["inserted"], 1)
        self.assertEqual(b["inserted"], 1)
        with self.db.connect() as con:
            rows = con.execute("SELECT content_id FROM queue ORDER BY id").fetchall()
        self.assertEqual([r[0] for r in rows], ["ad_a", "ad_b"])

    def test_sent_history_advances_rotation(self):
        record_content_sent(self.db, "camp", -1001, "ad_a")
        enqueue_campaign(self.db, "camp", run_key="next")
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT content_id FROM queue").fetchone()[0], "ad_b")

    def test_protected_and_never_post_fail_closed(self):
        with self.db.connect() as con:
            con.execute("UPDATE destinations SET protected=1 WHERE group_id=-1001")
        p = campaign_preview(self.db, "camp")
        self.assertEqual(p["selected"], 0)
        self.assertEqual(p["skipped"]["protected"], 1)
        with self.db.connect() as con:
            con.execute("UPDATE destinations SET protected=0,never_auto_post=1 WHERE group_id=-1001")
        p = campaign_preview(self.db, "camp")
        self.assertEqual(p["selected"], 0)
        self.assertEqual(p["skipped"]["never_auto_post"], 1)

    def test_exclude_tags_override_include(self):
        with self.db.connect() as con:
            con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(-1001,'blocked')")
            con.execute("UPDATE campaigns SET exclude_tags='blocked' WHERE campaign_id='camp'")
        p = campaign_preview(self.db, "camp")
        self.assertEqual(p["selected"], 0)
        self.assertEqual(p["skipped"]["exclude_tags"], 1)

    def test_conflict_gap_spaces_pending_jobs(self):
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET conflict_gap_seconds=3600 WHERE campaign_id='camp'")
        enqueue_campaign(self.db, "camp", run_key="one")
        enqueue_campaign(self.db, "camp", run_key="two")
        with self.db.connect() as con:
            rows = con.execute("SELECT due_at FROM queue ORDER BY id").fetchall()
        a = datetime.fromisoformat(rows[0][0]); b = datetime.fromisoformat(rows[1][0])
        self.assertGreaterEqual((b-a).total_seconds(), 3600)

    def test_content_inbox_import(self):
        inbox = self.root / "content" / "inbox" / "Fresh Ad"
        inbox.mkdir(parents=True)
        (inbox / "caption.txt").write_text("Fresh caption", encoding="utf-8")
        (inbox / "one.jpg").write_bytes(b"x")
        results = import_content_inbox(self.db, self.root / "content")
        self.assertEqual(results[0]["content_id"], "fresh_ad")
        with self.db.connect() as con:
            row = con.execute("SELECT caption,media_json FROM content WHERE content_id='fresh_ad'").fetchone()
        self.assertEqual(row["caption"], "Fresh caption")
        self.assertIn("one.jpg", row["media_json"])
        self.assertFalse(inbox.exists())

    def test_clone_campaign_copies_variants_but_stays_disabled(self):
        clone_campaign(self.db, "camp", "camp_copy", "Copy")
        with self.db.connect() as con:
            c = con.execute("SELECT enabled,name FROM campaigns WHERE campaign_id='camp_copy'").fetchone()
            n = con.execute("SELECT COUNT(*) FROM campaign_content WHERE campaign_id='camp_copy' AND enabled=1").fetchone()[0]
        self.assertEqual(c["enabled"], 0)
        self.assertEqual(c["name"], "Copy")
        self.assertEqual(n, 2)

    def test_system_tags_reflect_access_and_mode(self):
        refresh_system_tags(self.db)
        with self.db.connect() as con:
            tags = {r[0] for r in con.execute("SELECT tag FROM destination_tags WHERE group_id=-1001")}
        self.assertIn("auto_both_accounts", tags)
        self.assertIn("auto_text", tags)
        self.assertIn("main", tags)

    def test_schedule_simulation_does_not_enqueue(self):
        configure_interval(self.db, "camp", 3600, "Australia/Adelaide", start_in_seconds=0)
        rows = simulate_schedules(self.db, hours=3)
        self.assertGreaterEqual(len(rows), 3)
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM queue").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
