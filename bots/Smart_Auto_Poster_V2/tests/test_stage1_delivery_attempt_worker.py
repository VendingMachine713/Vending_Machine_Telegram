import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_autoposter.db import Database, utcnow
from smart_autoposter.delivery_ledger import attempts_for_job, finish_attempt, start_attempt
from smart_autoposter.worker import Worker


class SuccessPool:
    def __init__(self, ids=None):
        self.ids = ids or [901]
        self.calls = 0

    async def send(self, account, group_id, caption, media, mode, topic_id):
        self.calls += 1
        return list(self.ids)


class FailingPool:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    async def send(self, account, group_id, caption, media, mode, topic_id):
        self.calls += 1
        raise self.exc


class Stage1DeliveryAttemptWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,updated_at) VALUES('primary','p',1,1,'p',?)",
                (now,),
            )
            con.execute(
                "INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) VALUES('content','caption','[]',1,'ready',?,?)",
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
                "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('job','run','campaign',-1001,'content',?,'pending',?,?)",
                (now, now, now),
            )
            self.job_id = int(cur.lastrowid)
        self.auth = {"primary": {"authorized": True}}

    def tearDown(self):
        self.tmp.cleanup()

    def _queue(self):
        with self.db.connect() as con:
            return dict(con.execute("SELECT * FROM queue WHERE id=?", (self.job_id,)).fetchone())

    def test_successful_send_records_sent_attempt_and_queue(self):
        pool = SuccessPool([901, 902])
        worker = Worker(self.db, pool, min_send_gap_seconds=0)

        self.assertTrue(asyncio.run(worker.run_once(self.auth)))
        self.assertEqual(pool.calls, 1)
        self.assertEqual(self._queue()["status"], "sent")
        attempts = attempts_for_job(self.db, self.job_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["outcome"], "sent")
        self.assertEqual(attempts[0]["telegram_message_ids"], "[901, 902]")

    def test_send_failure_records_failed_attempt_and_retry_queue(self):
        pool = FailingPool(ConnectionError("temporary connection reset"))
        worker = Worker(self.db, pool, min_send_gap_seconds=0)

        self.assertTrue(asyncio.run(worker.run_once(self.auth)))
        self.assertEqual(pool.calls, 1)
        queue = self._queue()
        self.assertEqual(queue["status"], "retry")
        attempts = attempts_for_job(self.db, self.job_id)
        self.assertEqual(attempts[0]["outcome"], "failed")
        self.assertEqual(attempts[0]["error_kind"], "network")

    def test_ack_journal_failure_fails_closed_to_uncertain(self):
        pool = SuccessPool([777])
        worker = Worker(self.db, pool, min_send_gap_seconds=0)

        with patch("smart_autoposter.worker.mark_acknowledged", side_effect=RuntimeError("journal write failed")):
            self.assertTrue(asyncio.run(worker.run_once(self.auth)))

        self.assertEqual(pool.calls, 1)
        queue = self._queue()
        self.assertEqual(queue["status"], "uncertain")
        self.assertEqual(queue["error_kind"], "post_send_persistence")
        attempts = attempts_for_job(self.db, self.job_id)
        self.assertEqual(attempts[0]["outcome"], "uncertain")
        self.assertEqual(attempts[0]["telegram_message_ids"], "[777]")

    def test_secondary_bookkeeping_failure_does_not_downgrade_confirmed_send(self):
        pool = SuccessPool([888])
        worker = Worker(self.db, pool, min_send_gap_seconds=0)

        with patch("smart_autoposter.worker.record_content_sent", side_effect=RuntimeError("analytics write failed")):
            self.assertTrue(asyncio.run(worker.run_once(self.auth)))

        queue = self._queue()
        self.assertEqual(queue["status"], "sent")
        self.assertEqual(queue["telegram_message_ids"], "[888]")
        attempts = attempts_for_job(self.db, self.job_id)
        self.assertEqual(attempts[0]["outcome"], "sent")

    def test_startup_recovery_closes_open_attempt_as_uncertain(self):
        with self.db.connect() as con:
            con.execute("UPDATE queue SET status='sending' WHERE id=?", (self.job_id,))
        attempt = start_attempt(self.db, self.job_id, "primary")
        self.assertEqual(attempts_for_job(self.db, self.job_id)[0]["outcome"], "started")

        worker = Worker(self.db, SuccessPool(), min_send_gap_seconds=0)
        self.assertEqual(worker.recover_interrupted_sends(), 1)

        self.assertEqual(self._queue()["status"], "uncertain")
        ledger = attempts_for_job(self.db, self.job_id)[0]
        self.assertEqual(ledger["outcome"], "uncertain")
        self.assertEqual(worker.last_recovery_summary["delivery_attempts_reconciled"]["uncertain"], 1)

    def test_ledger_error_text_is_redacted(self):
        with self.db.connect() as con:
            con.execute("UPDATE queue SET status='sending' WHERE id=?", (self.job_id,))
        attempt = start_attempt(self.db, self.job_id, "primary")
        secret = "123456789:AAabcdefghijklmnopq"
        finish_attempt(self.db, attempt["id"], "failed", error_kind="test", error_text=f"token={secret}")
        row = attempts_for_job(self.db, self.job_id)[0]
        self.assertNotIn(secret, row["error_text"])
        self.assertIn("[REDACTED_BOT_TOKEN]", row["error_text"])


if __name__ == "__main__":
    unittest.main()
