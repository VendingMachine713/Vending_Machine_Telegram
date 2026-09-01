import asyncio
import sys
import types

# Build environment shim; production still uses real Telethon.
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

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from smart_autoposter.core import create_campaign, create_content
from smart_autoposter.db import Database, utcnow
from smart_autoposter.production import ProductionBootstrapSpec
from smart_autoposter.worker import Worker


class V330FastPassTests(unittest.TestCase):
    def _db(self):
        tmp = tempfile.TemporaryDirectory()
        db = Database(Path(tmp.name) / "db.sqlite3")
        db.init()
        return tmp, db

    def _base(self, db):
        now = utcnow()
        create_content(db, "content", "caption", [])
        create_campaign(db, "camp", "Campaign", "content", priority=100)
        with db.connect() as con:
            con.execute(
                "INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,health_score,consecutive_failures,updated_at) VALUES('primary','p',1,1,'p',100,0,?)",
                (now,),
            )
            for gid, name in [(-1001, "A"), (-1002, "B"), (-1003, "C")]:
                con.execute(
                    "INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(?,?,1,0,'primary','text',1,0,?)",
                    (gid, name, now),
                )
            con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active' WHERE campaign_id='camp'")
        return now

    def test_production_fast_pass_defaults_to_zero_spread(self):
        self.assertEqual(ProductionBootstrapSpec().spread_minutes, 0)

    def test_claim_prioritizes_clean_pending_before_due_retry_and_deferred(self):
        tmp, db = self._db()
        try:
            now = self._base(db)
            older = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
            with db.connect() as con:
                con.execute(
                    "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('retry','r','camp',-1001,'content',?,'retry',?,?)",
                    (older, now, now),
                )
                con.execute(
                    "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('deferred','r','camp',-1002,'content',?,'deferred',?,?)",
                    (older, now, now),
                )
                con.execute(
                    "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('pending','r','camp',-1003,'content',?,'pending',?,?)",
                    (utcnow(), now, now),
                )
            job = Worker(db, None, min_send_gap_seconds=0).claim()
            self.assertEqual(job["job_key"], "pending")
        finally:
            tmp.cleanup()

    def test_timeout_moves_job_to_uncertain_without_penalizing_health(self):
        tmp, db = self._db()
        try:
            now = self._base(db)
            with db.connect() as con:
                con.execute(
                    "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,max_attempts,created_at,updated_at) VALUES('j','r','camp',-1001,'content',?,'pending',0,4,?,?)",
                    (utcnow(), now, now),
                )

            class SlowPool:
                async def send(self, *args, **kwargs):
                    await asyncio.sleep(3600)

            worker = Worker(db, SlowPool(), min_send_gap_seconds=0, send_timeout_seconds=15)
            auth = {"primary": {"authorized": True}, "secondary": {"authorized": False}}

            async def force_timeout(awaitable, timeout):
                # Close the underlying coroutine so this local unit test does not
                # leave an un-awaited coroutine warning behind.
                if hasattr(awaitable, "close"):
                    awaitable.close()
                raise asyncio.TimeoutError

            with patch("smart_autoposter.worker.asyncio.wait_for", new=force_timeout):
                asyncio.run(worker.run_once(auth))

            with db.connect() as con:
                q = con.execute("SELECT status,error_kind,attempts FROM queue WHERE job_key='j'").fetchone()
                a = con.execute("SELECT health_score,consecutive_failures FROM accounts WHERE account_key='primary'").fetchone()
                d = con.execute("SELECT consecutive_failures FROM destinations WHERE group_id=-1001").fetchone()
            self.assertEqual(tuple(q), ("uncertain", "send_timeout_uncertain", 1))
            self.assertEqual(tuple(a), (100, 0))
            self.assertEqual(d[0], 0)
        finally:
            tmp.cleanup()

    def test_successful_send_applies_gap_instead_of_deferring_next_job(self):
        tmp, db = self._db()
        try:
            now = self._base(db)
            with db.connect() as con:
                con.execute(
                    "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('j','r','camp',-1001,'content',?,'pending',?,?)",
                    (utcnow(), now, now),
                )

            class Pool:
                async def send(self, *args, **kwargs):
                    return [123]

            worker = Worker(db, Pool(), min_send_gap_seconds=3, send_timeout_seconds=45)
            auth = {"primary": {"authorized": True}, "secondary": {"authorized": False}}
            with patch("smart_autoposter.worker.asyncio.sleep", new_callable=AsyncMock) as sleeper:
                asyncio.run(worker.run_once(auth))
                sleeper.assert_awaited_once_with(3)
            with db.connect() as con:
                q = con.execute("SELECT status FROM queue WHERE job_key='j'").fetchone()[0]
            self.assertEqual(q, "sent")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
