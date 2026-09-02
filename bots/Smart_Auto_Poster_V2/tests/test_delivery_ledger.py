import tempfile
import unittest
from pathlib import Path

from smart_autoposter.db import Database, utcnow
from smart_autoposter.delivery_ledger import (
    attempts_for_job,
    ensure_delivery_ledger,
    finish_attempt,
    mark_acknowledged,
    reconcile_open_attempts_from_queue,
    start_attempt,
)


class DeliveryLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        ensure_delivery_ledger(self.db)
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) VALUES('content','x','[]',1,'ready',?,?)",
                (now, now),
            )
            con.execute(
                "INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,priority,created_at,updated_at) VALUES('campaign','C','content',1,'active',50,?,?)",
                (now, now),
            )
            con.execute(
                "INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'G',1,0,'primary','text',1,0,?)",
                (now,),
            )
            cur = con.execute(
                "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('job','run','campaign',-1001,'content',?,'sending',?,?)",
                (now, now, now),
            )
            self.job_id = int(cur.lastrowid)

    def tearDown(self):
        self.tmp.cleanup()

    def test_attempt_lifecycle_records_telegram_ack_and_sent_outcome(self):
        attempt = start_attempt(self.db, self.job_id, "primary")
        self.assertEqual(attempt["attempt_no"], 1)
        mark_acknowledged(self.db, attempt["id"], [101, 102])
        finish_attempt(self.db, attempt["id"], "sent", message_ids=[101, 102])
        row = attempts_for_job(self.db, self.job_id)[0]
        self.assertEqual(row["outcome"], "sent")
        self.assertEqual(row["telegram_message_ids"], "[101, 102]")
        self.assertIsNotNone(row["acknowledged_at"])
        self.assertIsNotNone(row["finished_at"])

    def test_attempt_number_increments_across_retries(self):
        first = start_attempt(self.db, self.job_id, "primary")
        finish_attempt(self.db, first["id"], "failed", error_kind="network", error_text="temporary")
        second = start_attempt(self.db, self.job_id, "primary")
        self.assertEqual(first["attempt_no"], 1)
        self.assertEqual(second["attempt_no"], 2)

    def test_attempt_cannot_start_before_worker_claims_job(self):
        with self.db.connect() as con:
            con.execute("UPDATE queue SET status='pending' WHERE id=?", (self.job_id,))
        with self.assertRaisesRegex(RuntimeError, "requires sending state"):
            start_attempt(self.db, self.job_id, "primary")

    def test_restart_reconciliation_mirrors_uncertain_queue_state(self):
        attempt = start_attempt(self.db, self.job_id, "primary")
        mark_acknowledged(self.db, attempt["id"], [777])
        with self.db.connect() as con:
            con.execute(
                "UPDATE queue SET status='uncertain',error_kind='interrupted_send',last_error='restart',telegram_message_ids='[777]' WHERE id=?",
                (self.job_id,),
            )
        result = reconcile_open_attempts_from_queue(self.db, [self.job_id])
        self.assertEqual(result["uncertain"], 1)
        row = attempts_for_job(self.db, self.job_id)[0]
        self.assertEqual(row["outcome"], "uncertain")
        self.assertEqual(row["telegram_message_ids"], "[777]")

    def test_restart_reconciliation_can_close_acknowledged_attempt_from_sent_queue(self):
        attempt = start_attempt(self.db, self.job_id, "primary")
        mark_acknowledged(self.db, attempt["id"], [888])
        with self.db.connect() as con:
            con.execute(
                "UPDATE queue SET status='sent',telegram_message_ids='[888]',resolved_at=?,updated_at=? WHERE id=?",
                (utcnow(), utcnow(), self.job_id),
            )
        result = reconcile_open_attempts_from_queue(self.db, [self.job_id])
        self.assertEqual(result["sent"], 1)
        self.assertEqual(attempts_for_job(self.db, self.job_id)[0]["outcome"], "sent")


if __name__ == "__main__":
    unittest.main()
