import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Keep this suite runnable in environments without Telethon installed.
telethon = types.ModuleType("telethon")
class DummyClient: pass
telethon.TelegramClient = DummyClient
errs = types.SimpleNamespace()
for name in [
    "FloodWaitError", "SlowModeWaitError", "ChatWriteForbiddenError",
    "ChatSendMediaForbiddenError", "ChatSendPhotosForbiddenError",
    "ChatSendPlainForbiddenError", "UserBannedInChannelError",
]:
    setattr(errs, name, type(name, (Exception,), {}))
telethon.errors = errs
sys.modules.setdefault("telethon", telethon)

from smart_autoposter.db import Database, utcnow
from smart_autoposter.worker import Worker


class Stage1FoundationEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) VALUES('content','x','[]',1,'ready',?,?)", (now, now))
            con.execute("INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,priority,created_at,updated_at) VALUES('campaign','C','content',1,'active',50,?,?)", (now, now))
            con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,consecutive_failures,updated_at) VALUES(-1001,'healthy',1,0,'primary','text',1,0,0,?)", (now,))
            con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,consecutive_failures,updated_at) VALUES(-1002,'problem',1,0,'primary','text',1,0,4,?)", (now,))

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, key, group_id, status, *, due_at=None, attempts=0):
        due_at = due_at or (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,max_attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,4,?,?)",
                (key, "run", "campaign", group_id, "content", due_at, status, attempts, now, now),
            )

    def test_fresh_pending_work_beats_due_retry_and_deferred_work(self):
        self._job("retry", -1001, "retry")
        self._job("deferred", -1001, "deferred")
        self._job("pending", -1001, "pending")
        claimed = Worker(self.db, None).claim()
        self.assertEqual(claimed["job_key"], "pending")

    def test_clean_destination_beats_problem_destination_with_same_queue_class(self):
        self._job("problem", -1002, "pending")
        self._job("healthy", -1001, "pending")
        claimed = Worker(self.db, None).claim()
        self.assertEqual(claimed["job_key"], "healthy")

    def test_retry_backoff_is_exponential_and_bounded(self):
        self.assertEqual(Worker.retry_delay_seconds(1, "network"), 15)
        self.assertEqual(Worker.retry_delay_seconds(2, "network"), 30)
        self.assertEqual(Worker.retry_delay_seconds(3, "network"), 60)
        self.assertLessEqual(Worker.retry_delay_seconds(99, "network"), 900)
        self.assertEqual(Worker.retry_delay_seconds(1, "worker_busy"), 5)

    def test_interrupted_send_becomes_uncertain_not_retry(self):
        self._job("sending", -1001, "sending")
        worker = Worker(self.db, None)
        recovered = worker.recover_interrupted_sends()
        self.assertEqual(recovered, 1)
        with self.db.connect() as con:
            row = con.execute("SELECT status,error_kind FROM queue WHERE job_key='sending'").fetchone()
        self.assertEqual(row["status"], "uncertain")
        self.assertEqual(row["error_kind"], "interrupted_send")

    def test_retry_due_time_grows_after_repeated_failures(self):
        self._job("retry-backoff", -1001, "sending", attempts=1)
        with self.db.connect() as con:
            row = dict(con.execute("SELECT q.*, d.group_name FROM queue q JOIN destinations d ON d.group_id=q.group_id WHERE q.job_key='retry-backoff'").fetchone())
        before = datetime.now(timezone.utc)
        Worker(self.db, None).finish_error(row, "network: temporary", permanent=False, account=None, kind="network")
        with self.db.connect() as con:
            updated = con.execute("SELECT status,attempts,due_at FROM queue WHERE job_key='retry-backoff'").fetchone()
        due = datetime.fromisoformat(updated["due_at"])
        self.assertEqual(updated["status"], "retry")
        self.assertEqual(updated["attempts"], 2)
        self.assertGreaterEqual((due - before).total_seconds(), 29)


if __name__ == "__main__":
    unittest.main()
