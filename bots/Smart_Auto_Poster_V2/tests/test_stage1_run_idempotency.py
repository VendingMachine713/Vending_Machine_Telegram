import tempfile
import unittest
from pathlib import Path

from smart_autoposter.core import enqueue_campaign
from smart_autoposter.db import Database, utcnow
from smart_autoposter.delivery_ledger import ensure_delivery_ledger


class RunIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) VALUES('content','caption','[]',1,'ready',?,?)",
                (now, now),
            )
            con.execute(
                "INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,priority,created_at,updated_at) VALUES('campaign','Campaign','content',1,'active',50,?,?)",
                (now, now),
            )
            con.execute(
                "INSERT INTO campaign_content(campaign_id,content_id,position,weight,enabled,added_at) VALUES('campaign','content',0,1,1,?)",
                (now,),
            )
            con.execute(
                "INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'One',1,0,'primary','text',1,0,?)",
                (now,),
            )
            con.execute(
                "INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1002,'Two',1,0,'primary','text',0,0,?)",
                (now,),
            )
        ensure_delivery_ledger(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_replay_cannot_top_up_old_run_after_destination_change(self):
        first = enqueue_campaign(self.db, "campaign", run_key="run-1")
        self.assertEqual(first["inserted"], 1)
        with self.db.connect() as con:
            con.execute("UPDATE destinations SET enabled=1 WHERE group_id=-1002")

        replay = enqueue_campaign(self.db, "campaign", run_key="run-1")
        self.assertEqual(replay["inserted"], 0)
        self.assertEqual(replay["duplicates"], 2)
        with self.db.connect() as con:
            rows = con.execute("SELECT group_id FROM queue WHERE campaign_id='campaign' AND run_key='run-1' ORDER BY group_id").fetchall()
        self.assertEqual([r[0] for r in rows], [-1001])

    def test_new_run_after_change_gets_current_destination_set(self):
        enqueue_campaign(self.db, "campaign", run_key="run-1")
        with self.db.connect() as con:
            con.execute("UPDATE destinations SET enabled=1 WHERE group_id=-1002")
        second = enqueue_campaign(self.db, "campaign", run_key="run-2")
        self.assertEqual(second["inserted"], 2)
        with self.db.connect() as con:
            seals = con.execute("SELECT run_key,job_count FROM queue_run_seals WHERE campaign_id='campaign' ORDER BY run_key").fetchall()
        self.assertEqual([(r[0], r[1]) for r in seals], [("run-1", 1), ("run-2", 2)])

    def test_existing_queue_rows_are_backfilled_as_sealed(self):
        with self.db.connect() as con:
            con.execute("DROP TRIGGER IF EXISTS trg_queue_block_sealed_run")
            con.execute("DROP TRIGGER IF EXISTS trg_campaign_seal_completed_run")
            con.execute("DELETE FROM queue_run_seals")
            now = utcnow()
            con.execute(
                "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('legacy-job','legacy-run','campaign',-1001,'content',?,'pending',?,?)",
                (now, now, now),
            )
            con.execute("UPDATE destinations SET enabled=1 WHERE group_id=-1002")
        ensure_delivery_ledger(self.db)

        replay = enqueue_campaign(self.db, "campaign", run_key="legacy-run")
        self.assertEqual(replay["inserted"], 0)
        with self.db.connect() as con:
            count = con.execute("SELECT COUNT(*) FROM queue WHERE campaign_id='campaign' AND run_key='legacy-run'").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
