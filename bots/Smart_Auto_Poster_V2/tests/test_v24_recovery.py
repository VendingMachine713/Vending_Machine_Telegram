import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
import types
telethon = types.ModuleType("telethon")
class DummyClient: pass
telethon.TelegramClient = DummyClient
errs = types.SimpleNamespace()
for name in [
    "FloodWaitError", "SlowModeWaitError", "ChatWriteForbiddenError",
    "ChatSendMediaForbiddenError", "ChatSendPhotosForbiddenError",
    "ChatSendPlainForbiddenError", "UserBannedInChannelError",
    "ChannelPrivateError", "ChatAdminRequiredError", "PeerIdInvalidError",
    "TopicDeletedError", "MessageIdInvalidError",
]:
    setattr(errs, name, type(name, (Exception,), {}))
telethon.errors = errs
sys.modules.setdefault("telethon", telethon)

from smart_autoposter.db import Database, utcnow
from smart_autoposter.operations import expire_ineligible_jobs, record_update_history, recent_update_history
from smart_autoposter.worker import Worker


class RecoveryAndLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,health_score,updated_at) VALUES('primary','p',1,1,'P',100,?)", (now,))
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,health_score,updated_at) VALUES('secondary','s',1,1,'S',100,?)", (now,))
            con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'D',1,0,'primary','text',1,0,?)", (now,))
            con.execute("INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) VALUES('ad','hello','[]',1,'ready',?,?)", (now, now))
            con.execute("INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,last_preview_at,created_at,updated_at) VALUES('camp','C','ad',1,'active',?,?,?)", (now, now, now))
            con.execute("INSERT INTO campaign_content(campaign_id,content_id,position,weight,enabled,added_at) VALUES('camp','ad',0,1,1,?)", (now,))
            con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('j1','r','camp',-1001,'ad',?,'pending',?,?)", (now, now, now))
        self.worker = Worker(self.db, None, min_send_gap_seconds=0)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self):
        with self.db.connect() as con:
            return dict(con.execute("SELECT q.*,d.group_name FROM queue q JOIN destinations d ON d.group_id=q.group_id WHERE q.job_key='j1'").fetchone())

    def test_paused_campaign_jobs_are_not_claimed(self):
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET enabled=0,lifecycle_state='paused' WHERE campaign_id='camp'")
        self.assertIsNone(self.worker.claim())
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM queue WHERE job_key='j1'").fetchone()[0], "pending")

    def test_archived_campaign_jobs_expire(self):
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET enabled=0,lifecycle_state='archived' WHERE campaign_id='camp'")
        self.assertEqual(expire_ineligible_jobs(self.db), 1)
        with self.db.connect() as con:
            row = con.execute("SELECT status,error_kind FROM queue WHERE job_key='j1'").fetchone()
        self.assertEqual(tuple(row), ("expired", "campaign_ineligible"))

    def test_ended_campaign_jobs_expire(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET end_at=? WHERE campaign_id='camp'", (past,))
        self.assertEqual(expire_ineligible_jobs(self.db), 1)
        self.assertIsNone(self.worker.claim())

    def test_flood_wait_cools_account_not_destination(self):
        retry = (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat(timespec="seconds")
        self.worker.finish_error(self.job(), "flood_wait: test", retry_at=retry, account="primary", kind="flood_wait")
        with self.db.connect() as con:
            q = con.execute("SELECT status,error_kind FROM queue WHERE job_key='j1'").fetchone()
            d = con.execute("SELECT consecutive_failures FROM destinations WHERE group_id=-1001").fetchone()[0]
            a = con.execute("SELECT cooldown_until,health_score FROM accounts WHERE account_key='primary'").fetchone()
        self.assertEqual(tuple(q), ("retry", "flood_wait"))
        self.assertEqual(d, 0)
        self.assertEqual(a[0], retry)
        self.assertLess(a[1], 100)

    def test_slow_mode_defers_destination_without_penalty(self):
        retry = (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat(timespec="seconds")
        self.worker.finish_error(self.job(), "slow_mode: test", retry_at=retry, account="primary", kind="slow_mode")
        with self.db.connect() as con:
            d = con.execute("SELECT next_eligible_at,consecutive_failures FROM destinations WHERE group_id=-1001").fetchone()
            q = con.execute("SELECT status,error_kind FROM queue WHERE job_key='j1'").fetchone()
        self.assertEqual(d[0], retry)
        self.assertEqual(d[1], 0)
        self.assertEqual(tuple(q), ("retry", "slow_mode"))

    def test_network_error_does_not_quarantine_destination(self):
        self.worker.finish_error(self.job(), "network: down", account="primary", kind="network")
        with self.db.connect() as con:
            failures = con.execute("SELECT consecutive_failures FROM destinations WHERE group_id=-1001").fetchone()[0]
        self.assertEqual(failures, 0)

    def test_repeated_permanent_destination_failures_quarantine(self):
        for i in range(5):
            with self.db.connect() as con:
                con.execute("UPDATE queue SET status='pending',attempts=0 WHERE job_key='j1'")
            self.worker.finish_error(self.job(), "permission denied", permanent=True, account="primary", kind="ChatWriteForbiddenError")
        with self.db.connect() as con:
            d = con.execute("SELECT consecutive_failures,quarantine_until FROM destinations WHERE group_id=-1001").fetchone()
            q = con.execute("SELECT status FROM queue WHERE job_key='j1'").fetchone()[0]
        self.assertGreaterEqual(d[0], 5)
        self.assertTrue(d[1])
        self.assertEqual(q, "quarantined")

    def test_interrupted_send_becomes_uncertain(self):
        with self.db.connect() as con:
            con.execute("UPDATE queue SET status='sending' WHERE job_key='j1'")
        self.assertEqual(self.worker.recover_interrupted_sends(), 1)
        with self.db.connect() as con:
            row = con.execute("SELECT status,error_kind FROM queue WHERE job_key='j1'").fetchone()
        self.assertEqual(tuple(row), ("uncertain", "interrupted_send"))

    def test_update_history_round_trip(self):
        rid = record_update_history(self.db, "2.4.0-alpha", previous_version="2.2.3-alpha", package_name="v24.zip")
        rows = recent_update_history(self.db)
        self.assertEqual(rows[0]["id"], rid)
        self.assertEqual(rows[0]["version"], "2.4.0-alpha")
        self.assertEqual(rows[0]["previous_version"], "2.2.3-alpha")


if __name__ == '__main__':
    unittest.main()
