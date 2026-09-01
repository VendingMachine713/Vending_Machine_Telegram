import sys
import tempfile
import types
import unittest
from pathlib import Path

telethon = types.ModuleType("telethon")
telethon.TelegramClient = object
errs = types.SimpleNamespace()
for name in [
    "FloodWaitError", "SlowModeWaitError", "ChatWriteForbiddenError", "ChatSendMediaForbiddenError",
    "ChatSendPhotosForbiddenError", "ChatSendPlainForbiddenError", "UserBannedInChannelError",
    "ChannelPrivateError", "ChatAdminRequiredError", "PeerIdInvalidError", "TopicDeletedError", "MessageIdInvalidError",
]:
    setattr(errs, name, type(name, (Exception,), {}))
telethon.errors = errs
sys.modules.setdefault("telethon", telethon)

from smart_autoposter.db import Database, SCHEMA_VERSION, utcnow
from smart_autoposter.delivery_intelligence import delivery_diagnosis, failure_family, safe_recovery_plan
from smart_autoposter.worker import Worker


class V340DeliveryIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO content(content_id,caption,media_json,created_at,updated_at) VALUES('c','x','[]',?,?)", (now, now))
            con.execute("INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,created_at,updated_at) VALUES('camp','C','c',1,'active',?,?)", (now, now))
            con.execute("INSERT INTO destinations(group_id,group_name,enabled,needs_review,primary_access,updated_at) VALUES(-1,'Destination',1,0,1,?)", (now,))
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,health_score,updated_at) VALUES('primary','p',1,1,100,?)", (now,))

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, key="j", status="sending", attempts=0, max_attempts=4):
        now = utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,max_attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (key, "run", "camp", -1, "c", now, status, attempts, max_attempts, now, now))
            return dict(con.execute("SELECT * FROM queue WHERE job_key=?", (key,)).fetchone())

    def test_schema_v7_has_delivery_attempt_history(self):
        self.assertEqual(SCHEMA_VERSION, 20)
        with self.db.connect() as con:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("delivery_attempts", names)

    def test_failure_taxonomy_is_actionable(self):
        self.assertEqual(failure_family("send_timeout_uncertain", "uncertain"), "uncertain")
        self.assertEqual(failure_family("slow_mode", "retry"), "timing")
        self.assertEqual(failure_family("auth_session", "retry"), "account")
        self.assertEqual(failure_family("ChatWriteForbiddenError", "retry"), "permanent_destination")
        self.assertEqual(failure_family("network", "retry"), "transient")

    def test_worker_persists_attempt_history(self):
        job = self._job()
        Worker(self.db, None).finish_error(job, "network: reset", retry_at=utcnow(), account="primary", kind="network", duration_ms=321)
        with self.db.connect() as con:
            row = con.execute("SELECT outcome,error_kind,duration_ms,account_key FROM delivery_attempts WHERE queue_id=?", (job["id"],)).fetchone()
        self.assertEqual(tuple(row), ("retry", "network", 321, "primary"))

    def test_diagnosis_groups_problem_jobs_without_mutation(self):
        job = self._job()
        Worker(self.db, None).finish_error(job, "timeout", account="primary", kind="send_timeout_uncertain")
        result = delivery_diagnosis(self.db, hours=24, campaign_id="camp")
        self.assertEqual(result["families"]["uncertain"], 1)
        self.assertFalse(result["safety"]["mutated"])
        with self.db.connect() as con:
            status = con.execute("SELECT status FROM queue WHERE id=?", (job["id"],)).fetchone()[0]
        self.assertEqual(status, "uncertain")

    def test_recovery_never_auto_retries_uncertain(self):
        job = self._job()
        Worker(self.db, None).finish_error(job, "ambiguous", account="primary", kind="uncertain_telegram_ack")
        result = safe_recovery_plan(self.db, campaign_id="camp", apply=True)
        self.assertEqual(result["uncertain_preserved"], 1)
        self.assertEqual(result["changed"], 0)
        with self.db.connect() as con:
            status = con.execute("SELECT status FROM queue WHERE id=?", (job["id"],)).fetchone()[0]
        self.assertEqual(status, "uncertain")

    def test_recovery_closes_permanent_retry(self):
        job = self._job(status="retry", attempts=1)
        with self.db.connect() as con:
            con.execute("UPDATE queue SET error_kind='ChatWriteForbiddenError' WHERE id=?", (job["id"],))
        preview = safe_recovery_plan(self.db, apply=False)
        self.assertEqual(preview["actions"][0]["action"], "close_impossible_retry")
        self.assertEqual(safe_recovery_plan(self.db, apply=True)["changed"], 1)
        with self.db.connect() as con:
            status = con.execute("SELECT status FROM queue WHERE id=?", (job["id"],)).fetchone()[0]
        self.assertEqual(status, "failed")


if __name__ == "__main__":
    unittest.main()
