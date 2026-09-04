import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from smart_autoposter.core import create_campaign, create_content, enqueue_campaign, validate, repair_routing_preferences
from smart_autoposter.db import Database, utcnow
from smart_autoposter.scheduler import Scheduler, configure_interval, next_daily_run
from smart_autoposter.time_rules import quiet_until


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "data" / "test.sqlite3")
        self.db.init()
        self.media = self.root / "one.jpg"
        self.media.write_bytes(b"not-a-real-jpeg-but-file-exists")
        now = utcnow()
        with self.db.connect() as con:
            con.execute('''INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at)
                           VALUES(-1001,'Test Group',1,1,'primary','photo',1,0,?)''', (now,))
            con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(-1001,'main')")
        create_content(self.db, "AD1", "hello", [str(self.media)])
        create_campaign(self.db, "C1", "Campaign 1", "AD1", tags="main")
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active' WHERE campaign_id='C1'")

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_and_validation(self):
        self.assertEqual(validate(self.db), [])
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "7")

    def test_enqueue_duplicate_guard_per_run(self):
        a = enqueue_campaign(self.db, "C1", run_key="test-run")
        b = enqueue_campaign(self.db, "C1", run_key="test-run")
        c = enqueue_campaign(self.db, "C1", run_key="next-run")
        self.assertEqual(a["inserted"], 1)
        self.assertEqual(b["duplicates"], 1)
        self.assertEqual(c["inserted"], 1)

    def test_scheduler_enqueues_due_interval(self):
        configure_interval(self.db, "C1", 3600, "Australia/Adelaide", start_in_seconds=0)
        result = Scheduler(self.db).tick()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["inserted"], 1)
        with self.db.connect() as con:
            row = con.execute("SELECT next_run_at,last_run_at FROM campaign_schedules WHERE campaign_id='C1'").fetchone()
            self.assertIsNotNone(row["last_run_at"])
            self.assertGreater(row["next_run_at"], row["last_run_at"])

    def test_quiet_hours_overnight(self):
        now = datetime(2026, 8, 27, 13, 0, tzinfo=timezone.utc)  # 22:30 Adelaide (UTC+9:30)
        until = quiet_until(now, "22:00", "07:00", "Australia/Adelaide")
        self.assertIsNotNone(until)
        self.assertGreater(until, now)

    def test_online_backup_contains_committed_state(self):
        backup = self.root / "backup.sqlite3"
        self.db.backup_to(backup)
        restored = Database(backup)
        with restored.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 1)

    def test_daily_schedule_future(self):
        now = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)
        nxt = next_daily_run(now, ["09:00","19:00"], list(range(7)), "Australia/Adelaide")
        self.assertGreater(nxt, now)

    def test_repair_routing_preferences_follows_live_access(self):
        now = utcnow()
        with self.db.connect() as con:
            con.execute("UPDATE destinations SET primary_access=1,secondary_access=0,preferred_account='secondary',updated_at=? WHERE group_id=-1001", (now,))
            con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1002,'Secondary Only',0,1,'primary','text',1,0,?)", (now,))
            con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1003,'Both',1,1,'secondary','text',1,0,?)", (now,))
        result = repair_routing_preferences(self.db)
        self.assertEqual(result["to_primary"], 1)
        self.assertEqual(result["to_secondary"], 1)
        self.assertEqual(result["total"], 2)
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT preferred_account FROM destinations WHERE group_id=-1001").fetchone()[0], "primary")
            self.assertEqual(con.execute("SELECT preferred_account FROM destinations WHERE group_id=-1002").fetchone()[0], "secondary")
            self.assertEqual(con.execute("SELECT preferred_account FROM destinations WHERE group_id=-1003").fetchone()[0], "secondary")


if __name__ == "__main__":
    unittest.main()
