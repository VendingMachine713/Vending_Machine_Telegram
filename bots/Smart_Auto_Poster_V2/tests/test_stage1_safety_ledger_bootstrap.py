import tempfile
import unittest
from pathlib import Path

from smart_autoposter.core import create_campaign, create_content, enqueue_campaign
from smart_autoposter.db import Database, utcnow


class SafetyLedgerBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'G',1,0,'primary','text',1,0,?)",
                (now,),
            )
            con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(-1001,'main')")
        create_content(self.db, "content", "hello", [])
        create_campaign(self.db, "camp", "Campaign", "content", tags="main")
        with self.db.connect() as con:
            con.execute(
                "UPDATE campaigns SET enabled=1,lifecycle_state='active',last_preview_at=? WHERE campaign_id='camp'",
                (utcnow(),),
            )

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_enqueue_bootstraps_run_seal_without_worker_startup(self):
        # Deliberately do not call ensure_delivery_ledger(). Enqueue itself must make
        # its duplicate-safety journal available before creating production work.
        first = enqueue_campaign(self.db, "camp", run_key="cold-start")
        self.assertEqual(first["inserted"], 1)
        with self.db.connect() as con:
            seal = con.execute(
                "SELECT job_count FROM queue_run_seals WHERE campaign_id='camp' AND run_key='cold-start'"
            ).fetchone()
            self.assertIsNotNone(seal)
            self.assertEqual(seal[0], 1)

        replay = enqueue_campaign(self.db, "camp", run_key="cold-start")
        self.assertEqual(replay["inserted"], 0)
        self.assertEqual(replay["duplicates"], 1)
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM queue WHERE run_key='cold-start'").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT completed_cycles FROM campaigns WHERE campaign_id='camp'").fetchone()[0], 1)

    def test_dry_run_does_not_create_safety_tables(self):
        result = enqueue_campaign(self.db, "camp", dry_run=True, run_key="preview-only")
        self.assertEqual(result["inserted"], 0)
        with self.db.connect() as con:
            table = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='queue_run_seals'"
            ).fetchone()
            self.assertIsNone(table)


if __name__ == "__main__":
    unittest.main()
