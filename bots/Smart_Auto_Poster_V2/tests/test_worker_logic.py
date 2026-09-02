import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The build environment intentionally has no Telethon package. A tiny import shim lets
# us exercise the worker's local account-selection logic without pretending to test
# Telegram network behaviour.
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


class WorkerSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,updated_at) VALUES('primary','p',1,1,'p',?)", (now,))
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,updated_at) VALUES('secondary','s',1,1,'s',?)", (now,))
        self.auth = {"primary":{"authorized":True},"secondary":{"authorized":True}}
        self.job = {"preferred_account":"primary","primary_access":1,"secondary_access":1,"account_key":None}

    def tearDown(self):
        self.tmp.cleanup()

    def test_prefers_primary_when_available(self):
        w = Worker(self.db, None, min_send_gap_seconds=3)
        key, until, reason = w.choose_account(self.job, self.auth)
        self.assertEqual(key, "primary")
        self.assertIsNone(until)

    def test_falls_back_when_primary_is_cooling(self):
        future = (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(timespec="seconds")
        with self.db.connect() as con:
            con.execute("UPDATE accounts SET cooldown_until=? WHERE account_key='primary'", (future,))
        w = Worker(self.db, None, min_send_gap_seconds=3)
        key, until, reason = w.choose_account(self.job, self.auth)
        self.assertEqual(key, "secondary")

    def test_pinned_retry_does_not_switch_accounts(self):
        future = (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(timespec="seconds")
        with self.db.connect() as con:
            con.execute("UPDATE accounts SET cooldown_until=? WHERE account_key='primary'", (future,))
        job = dict(self.job); job["account_key"]="primary"
        w = Worker(self.db, None, min_send_gap_seconds=3)
        key, until, reason = w.choose_account(job, self.auth)
        self.assertIsNone(key)
        self.assertIsNotNone(until)
        self.assertEqual(reason, "account_cooldown_or_pacing")

    def test_recent_success_enforces_pacing(self):
        recent = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db.connect() as con:
            con.execute("UPDATE accounts SET last_success_at=? WHERE account_key='primary'", (recent,))
            con.execute("UPDATE accounts SET last_success_at=? WHERE account_key='secondary'", (recent,))
        w = Worker(self.db, None, min_send_gap_seconds=60)
        key, until, reason = w.choose_account(self.job, self.auth)
        self.assertIsNone(key)
        self.assertIsNotNone(until)
        self.assertEqual(reason, "account_cooldown_or_pacing")


if __name__ == "__main__":
    unittest.main()

class WorkerContentSelectionTests(unittest.TestCase):
    def test_worker_uses_queue_selected_content_and_records_usage(self):
        import asyncio
        from smart_autoposter.core import add_campaign_content, create_campaign, create_content, enqueue_campaign

        class Pool:
            def __init__(self): self.sent = []
            async def send(self, account, group_id, caption, media, mode, topic_id):
                self.sent.append((account, group_id, caption, list(media), mode, topic_id))
                return [777]

        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "db.sqlite3"); db.init(); now = utcnow()
            with db.connect() as con:
                con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,updated_at) VALUES('primary','p',1,1,'p',?)", (now,))
                con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,updated_at) VALUES('secondary','s',1,1,'s',?)", (now,))
                con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'T',1,0,'primary','text',1,0,?)", (now,))
                con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(-1001,'main')")
            create_content(db, "a", "caption A", [])
            create_content(db, "b", "caption B", [])
            create_campaign(db, "c", "C", "a", tags="main")
            add_campaign_content(db, "c", "b", position=1)
            with db.connect() as con: con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active',last_preview_at=? WHERE campaign_id='c'", (utcnow(),))
            enqueue_campaign(db, "c", run_key="first")
            enqueue_campaign(db, "c", run_key="second")
            # Cancel first so worker claims second, which should have variant b.
            with db.connect() as con: con.execute("UPDATE queue SET status='cancelled' WHERE id=(SELECT MIN(id) FROM queue)")
            pool = Pool(); worker = Worker(db, pool, min_send_gap_seconds=0)
            auth = {"primary":{"authorized":True},"secondary":{"authorized":True}}
            asyncio.run(worker.run_once(auth))
            self.assertEqual(pool.sent[0][2], "caption B")
            with db.connect() as con:
                usage = con.execute("SELECT use_count FROM content_usage WHERE campaign_id='c' AND group_id=-1001 AND content_id='b'").fetchone()
            self.assertEqual(usage[0], 1)
