import tempfile
import unittest
from pathlib import Path

from smart_autoposter.core import enqueue_campaign
from smart_autoposter.db import Database, utcnow
from smart_autoposter.delivery_ledger import ensure_delivery_ledger, start_attempt
from smart_autoposter.integrity import integrity_report


class LedgerIntegrityTests(unittest.TestCase):
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
        ensure_delivery_ledger(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_ledgers_are_healthy(self):
        enqueue_campaign(self.db, "campaign", run_key="run-1")
        report = integrity_report(self.db)
        self.assertTrue(report["healthy"], report["issues"])
        self.assertEqual(report["issue_counts"]["unsealed_queue_runs"], 0)
        self.assertEqual(report["issue_counts"]["sealed_run_count_mismatch"], 0)

    def test_open_delivery_attempt_on_uncertain_queue_is_detected(self):
        enqueue_campaign(self.db, "campaign", run_key="run-1")
        with self.db.connect() as con:
            job_id = con.execute("SELECT id FROM queue WHERE run_key='run-1'").fetchone()[0]
            con.execute("UPDATE queue SET status='sending' WHERE id=?", (job_id,))
        start_attempt(self.db, job_id, "primary")
        with self.db.connect() as con:
            con.execute(
                "UPDATE queue SET status='uncertain',error_kind='interrupted_send',last_error='needs reconciliation' WHERE id=?",
                (job_id,),
            )
        report = integrity_report(self.db)
        self.assertEqual(report["issue_counts"]["delivery_open_on_resolved_queue"], 1)

    def test_acknowledged_attempt_without_message_ids_is_detected(self):
        enqueue_campaign(self.db, "campaign", run_key="run-1")
        with self.db.connect() as con:
            job_id = con.execute("SELECT id FROM queue WHERE run_key='run-1'").fetchone()[0]
            con.execute("UPDATE queue SET status='sending' WHERE id=?", (job_id,))
        attempt = start_attempt(self.db, job_id, "primary")
        with self.db.connect() as con:
            con.execute("UPDATE delivery_attempts SET outcome='acknowledged',acknowledged_at=? WHERE id=?", (utcnow(), attempt["id"]))
        report = integrity_report(self.db)
        self.assertEqual(report["issue_counts"]["acknowledged_without_message_ids"], 1)

    def test_run_seal_job_count_mismatch_is_detected(self):
        enqueue_campaign(self.db, "campaign", run_key="run-1")
        with self.db.connect() as con:
            con.execute("DELETE FROM queue WHERE run_key='run-1'")
        report = integrity_report(self.db)
        self.assertEqual(report["issue_counts"]["sealed_run_count_mismatch"], 1)

    def test_unsealed_existing_run_is_detected(self):
        enqueue_campaign(self.db, "campaign", run_key="run-1")
        with self.db.connect() as con:
            con.execute("DELETE FROM queue_run_seals WHERE campaign_id='campaign' AND run_key='run-1'")
        report = integrity_report(self.db)
        self.assertEqual(report["issue_counts"]["unsealed_queue_runs"], 1)


if __name__ == "__main__":
    unittest.main()
