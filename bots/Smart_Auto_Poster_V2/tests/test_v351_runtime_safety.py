import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Build/test environments may intentionally omit Telethon.  Mirror the project's
# existing local-worker test shim so these tests verify queue/safety behaviour
# without pretending to exercise Telegram network I/O.
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
from smart_autoposter.safety import SafetyController
from smart_autoposter.worker import Worker


class V351CircuitBreakerSignalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "db.sqlite3")
        self.db.init()

    def tearDown(self):
        self.tmp.cleanup()

    def test_timing_backpressure_events_do_not_trip_breaker(self):
        safety = SafetyController(
            self.db,
            failure_threshold=3,
            window_minutes=10,
            pause_minutes=30,
            failure_ratio=0.75,
        )
        timing_types = ["slow_mode", "flood_wait", "worker_busy", "send_timing"]
        for i in range(12):
            self.db.event("WARNING", timing_types[i % len(timing_types)], f"timing {i}")

        state = safety.evaluate()
        self.assertFalse(state.paused)
        self.assertEqual(state.failures, 0)
        self.assertEqual(state.successes, 0)

    def test_uncertain_send_counts_as_risky_breaker_outcome(self):
        safety = SafetyController(
            self.db,
            failure_threshold=3,
            window_minutes=10,
            pause_minutes=30,
            failure_ratio=0.75,
        )
        for i in range(3):
            self.db.event("WARNING", "uncertain_send", f"uncertain {i}")
        self.db.event("INFO", "send_success", "success")

        state = safety.evaluate()
        self.assertTrue(state.paused)
        self.assertFalse(state.manual)
        self.assertEqual(state.failures, 3)
        self.assertEqual(state.successes, 1)
        self.assertIn("failed/uncertain", state.reason or "")

    def test_true_send_failures_still_trip_breaker(self):
        safety = SafetyController(
            self.db,
            failure_threshold=3,
            window_minutes=10,
            pause_minutes=30,
            failure_ratio=1.0,
        )
        for i in range(3):
            self.db.event("ERROR", "send_failure", f"failure {i}")
        self.assertTrue(safety.evaluate().paused)


class V351WorkerTimingEventTests(unittest.TestCase):
    def _build_job(self):
        tmp = tempfile.TemporaryDirectory()
        db = Database(Path(tmp.name) / "db.sqlite3")
        db.init()
        now = utcnow()
        with db.connect() as con:
            con.execute(
                "INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,health_score,consecutive_failures,updated_at) "
                "VALUES('primary','p',1,1,'p',100,0,?)",
                (now,),
            )
            con.execute(
                "INSERT INTO destinations(group_id,group_name,primary_access,preferred_account,mode,enabled,needs_review,updated_at) "
                "VALUES(-1,'Test',1,'primary','photo',1,0,?)",
                (now,),
            )
            con.execute(
                "INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) "
                "VALUES('c','x','[]',1,'ready',?,?)",
                (now, now),
            )
            con.execute(
                "INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,created_at,updated_at) "
                "VALUES('camp','Camp','c',1,'active',?,?)",
                (now, now),
            )
            con.execute(
                "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,max_attempts,created_at,updated_at) "
                "VALUES('j','r','camp',-1,'c',?,'sending',3,4,?,?)",
                (now, now, now),
            )
            job = dict(con.execute("SELECT * FROM queue WHERE job_key='j'").fetchone())
        return tmp, db, job

    def test_timing_errors_record_specific_event_not_send_failure(self):
        for kind in ("slow_mode", "flood_wait", "worker_busy"):
            with self.subTest(kind=kind):
                tmp, db, job = self._build_job()
                try:
                    retry_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(timespec="seconds")
                    Worker(db, None).finish_error(
                        job,
                        f"{kind}: test",
                        retry_at=retry_at,
                        account="primary",
                        kind=kind,
                    )
                    with db.connect() as con:
                        event_types = [r[0] for r in con.execute("SELECT event_type FROM events ORDER BY id").fetchall()]
                        q = con.execute("SELECT status,attempts,error_kind FROM queue WHERE job_key='j'").fetchone()
                    self.assertIn(kind, event_types)
                    self.assertNotIn("send_failure", event_types)
                    self.assertEqual(tuple(q), ("deferred", 3, kind))
                finally:
                    tmp.cleanup()

    def test_uncertain_ack_records_uncertain_send(self):
        tmp, db, job = self._build_job()
        try:
            Worker(db, None).finish_error(
                job,
                "uncertain_telegram_ack: test",
                account="primary",
                kind="uncertain_telegram_ack",
            )
            with db.connect() as con:
                event_types = [r[0] for r in con.execute("SELECT event_type FROM events ORDER BY id").fetchall()]
                q = con.execute("SELECT status,error_kind FROM queue WHERE job_key='j'").fetchone()
            self.assertIn("uncertain_send", event_types)
            self.assertNotIn("send_failure", event_types)
            self.assertEqual(tuple(q), ("uncertain", "uncertain_telegram_ack"))
        finally:
            tmp.cleanup()


class V351WindowsLivenessTests(unittest.TestCase):
    def test_autostart_has_periodic_self_heal_and_duplicate_guard(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "INSTALL_AUTOSTART.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("RecoveryIntervalMinutes = 5", text)
        self.assertIn("-RepetitionInterval", text)
        self.assertIn("-MultipleInstances IgnoreNew", text)
        self.assertIn("-AllowStartIfOnBatteries", text)
        self.assertIn("-DontStopIfGoingOnBatteries", text)
        self.assertIn("/SC MINUTE", text)
        status = (root / "AUTOSTART_STATUS.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Triggers:", status)
        self.assertIn("Repetition.Interval", status)
        self.assertIn("Multiple instances:", status)


if __name__ == "__main__":
    unittest.main()
