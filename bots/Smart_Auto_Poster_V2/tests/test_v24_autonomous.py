import json
import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from smart_autoposter import __version__
from smart_autoposter.admin_bot import TelegramAdminController, accounts_text, content_text, dashboard_text, search_destinations_text
from smart_autoposter.analytics import analytics_snapshot
from smart_autoposter.content_library import import_content_inbox
from smart_autoposter.core import campaign_preview, create_campaign, create_content, enqueue_campaign
from smart_autoposter.db import Database, utcnow
from smart_autoposter.maintenance import database_integrity, generate_diagnostics
from smart_autoposter.notifications import NotificationManager, severity_at_least
from smart_autoposter.operations import (
    bulk_destination_action,
    enforce_queue_limits,
    manage_job,
    mark_campaign_previewed,
    set_campaign_gap,
    set_campaign_state,
    set_content_state,
    set_content_tags,
)
from smart_autoposter.redaction import redact_text
from smart_autoposter.safety import SafetyController
from smart_autoposter.scheduler import Scheduler, configure_once
from smart_autoposter.templates import create_from_template, list_templates
from smart_autoposter.watchdog import Watchdog


class V24AutonomousTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = Path.cwd()
        os.chdir(self.root)
        self.db = Database(self.root / "data" / "test.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO destinations(group_id,group_name,username,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at)
                   VALUES(-1001,'Main Destination','main_dest',1,1,'primary','text',1,0,?)""",
                (now,),
            )
            con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(-1001,'main')")
            con.execute(
                "INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,health_score,updated_at) VALUES('primary','p',1,1,'Primary',100,?)",
                (now,),
            )
            con.execute(
                "INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,health_score,updated_at) VALUES('secondary','s',1,1,'Secondary',100,?)",
                (now,),
            )
        create_content(self.db, "ad_a", "Caption A", [])
        create_campaign(self.db, "camp", "Campaign", "ad_a", tags="main")

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def _preview_activate(self, campaign="camp"):
        campaign_preview(self.db, campaign)
        mark_campaign_previewed(self.db, campaign)
        set_campaign_state(self.db, campaign, "active")

    def _enqueue(self, run_key="r1"):
        self._preview_activate()
        return enqueue_campaign(self.db, "camp", run_key=run_key)

    def test_schema_v5_has_autonomous_tables(self):
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "20")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in {"notifications", "heartbeats", "audit_log", "update_history", "campaign_relations", "content_tags"}:
                self.assertIn(name, tables)
            self.assertIn("error_kind", {r[1] for r in con.execute("PRAGMA table_info(queue)")})

    def test_preview_moves_draft_to_ready(self):
        mark_campaign_previewed(self.db, "camp")
        with self.db.connect() as con:
            row = con.execute("SELECT lifecycle_state,last_preview_at FROM campaigns WHERE campaign_id='camp'").fetchone()
        self.assertEqual(row["lifecycle_state"], "ready")
        self.assertTrue(row["last_preview_at"])

    def test_activation_requires_preview(self):
        with self.assertRaisesRegex(RuntimeError, "Preview"):
            set_campaign_state(self.db, "camp", "active")

    def test_activation_after_preview(self):
        self._preview_activate()
        with self.db.connect() as con:
            row = con.execute("SELECT lifecycle_state,enabled FROM campaigns WHERE campaign_id='camp'").fetchone()
        self.assertEqual(tuple(row), ("active", 1))

    def test_archive_disables_schedule(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="minutes")
        configure_once(self.db, "camp", future, "Australia/Adelaide")
        mark_campaign_previewed(self.db, "camp")
        set_campaign_state(self.db, "camp", "archived")
        with self.db.connect() as con:
            enabled = con.execute("SELECT enabled FROM campaign_schedules WHERE campaign_id='camp'").fetchone()[0]
        self.assertEqual(enabled, 0)

    def test_duplicate_content_fingerprint_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Duplicate content"):
            create_content(self.db, "ad_duplicate", "Caption A", [])

    def test_content_tags_add_and_remove(self):
        tags = set_content_tags(self.db, "ad_a", add=["Product", "Main"])
        self.assertEqual(tags, ["main", "product"])
        tags = set_content_tags(self.db, "ad_a", remove=["main"])
        self.assertEqual(tags, ["product"])

    def test_content_disable_blocked_when_active(self):
        self._preview_activate()
        with self.assertRaisesRegex(RuntimeError, "active campaign"):
            set_content_state(self.db, "ad_a", "disabled")

    def test_content_inbox_duplicate_is_rejected(self):
        source = self.root / "content" / "inbox" / "Copy Ad"
        source.mkdir(parents=True)
        (source / "caption.txt").write_text("Caption A", encoding="utf-8")
        result = import_content_inbox(self.db, self.root / "content")
        self.assertEqual(result[0]["status"], "duplicate")
        self.assertTrue(any((self.root / "content" / "rejected").iterdir()))

    def test_queue_total_capacity_guard(self):
        self._enqueue()
        with self.assertRaisesRegex(RuntimeError, "MAX_QUEUE_SIZE"):
            enforce_queue_limits(
                self.db,
                add_count=1,
                campaign_id="camp",
                group_ids=[-1001],
                max_queue_size=1,
                max_pending_per_campaign=10,
                max_pending_per_destination=10,
            )

    def test_queue_campaign_capacity_guard(self):
        self._enqueue()
        with self.assertRaisesRegex(RuntimeError, "MAX_PENDING_PER_CAMPAIGN"):
            enforce_queue_limits(self.db, add_count=1, campaign_id="camp", group_ids=[-1001], max_queue_size=10, max_pending_per_campaign=1, max_pending_per_destination=10)

    def test_queue_destination_capacity_guard(self):
        self._enqueue()
        with self.assertRaisesRegex(RuntimeError, "MAX_PENDING_PER_DESTINATION"):
            enforce_queue_limits(self.db, add_count=1, campaign_id="camp", group_ids=[-1001], max_queue_size=10, max_pending_per_campaign=10, max_pending_per_destination=1)

    def test_job_defer_cancel_retry(self):
        self._enqueue()
        with self.db.connect() as con:
            jid = con.execute("SELECT id FROM queue").fetchone()[0]
        manage_job(self.db, jid, "defer", minutes=10)
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM queue WHERE id=?", (jid,)).fetchone()[0], "deferred")
        manage_job(self.db, jid, "cancel")
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM queue WHERE id=?", (jid,)).fetchone()[0], "cancelled")
        manage_job(self.db, jid, "retry")
        with self.db.connect() as con:
            row = con.execute("SELECT status,resolved_at FROM queue WHERE id=?", (jid,)).fetchone()
        self.assertEqual(row["status"], "retry")
        self.assertIsNone(row["resolved_at"])

    def test_bulk_destination_protect_and_never(self):
        n = bulk_destination_action(self.db, tag="main", protect=True)
        self.assertEqual(n, 1)
        n = bulk_destination_action(self.db, tag="main", never_auto_post=True)
        self.assertEqual(n, 1)
        with self.db.connect() as con:
            row = con.execute("SELECT protected,never_auto_post,enabled FROM destinations WHERE group_id=-1001").fetchone()
        self.assertEqual(tuple(row), (1, 1, 0))

    def test_notification_dedupe(self):
        nm = NotificationManager(self.db)
        a = nm.emit("IMPORTANT", "One", "Message", dedupe_key="same")
        b = nm.emit("IMPORTANT", "Two", "Different", dedupe_key="same")
        self.assertEqual(a, b)
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 1)

    def test_notification_dedupe_window_requeues_old(self):
        nm = NotificationManager(self.db)
        nid = nm.emit("IMPORTANT", "One", "Message", dedupe_key="repeat")
        nm.mark_sent(nid)
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
        with self.db.connect() as con:
            con.execute("UPDATE notifications SET created_at=? WHERE id=?", (old, nid))
        same = nm.emit("CRITICAL", "Again", "Again message", dedupe_key="repeat", dedupe_window_seconds=3600)
        self.assertEqual(nid, same)
        with self.db.connect() as con:
            row = con.execute("SELECT status,severity,title FROM notifications WHERE id=?", (nid,)).fetchone()
        self.assertEqual(tuple(row), ("pending", "CRITICAL", "Again"))

    def test_notification_severity_filter(self):
        self.assertFalse(severity_at_least("WARNING", "IMPORTANT"))
        self.assertTrue(severity_at_least("CRITICAL", "IMPORTANT"))

    def test_watchdog_detects_stale(self):
        wd = Watchdog(self.db, stale_seconds=30)
        wd.beat("service", "ok")
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
        with self.db.connect() as con:
            con.execute("UPDATE heartbeats SET last_seen_at=? WHERE component='service'", (old,))
        problems = wd.evaluate(("service",))
        self.assertTrue(any("stale heartbeat" in p for p in problems))

    def test_database_integrity(self):
        result = database_integrity(self.db)
        self.assertTrue(result["ok"])

    def test_redaction(self):
        fake_token = "123456789:" + "AAFakeTokenForRedactionTest_1234567890"
        fake_hash = "01234567" * 4
        fake_phone = "+61" + "400000000"
        fake_code = "54321"
        raw = f"token {fake_token} hash {fake_hash} phone {fake_phone} login code: {fake_code}"
        clean = redact_text(raw)
        self.assertNotIn("AAFake", clean)
        self.assertNotIn("01234", clean)
        self.assertNotIn(fake_phone, clean)
        self.assertNotIn(fake_code, clean)

    def test_diagnostics_excludes_secrets_and_redacts_logs(self):
        fake_token = "123456789:" + "AAFakeTokenForRedactionTest_1234567890"
        fake_phone = "+61" + "400000000"
        log_dir = self.root / "logs"; log_dir.mkdir()
        backup_dir = self.root / "backups"; backup_dir.mkdir()
        diag_dir = self.root / "diagnostics"; diag_dir.mkdir()
        cache_dir = self.root / "cache"; cache_dir.mkdir()
        (self.root / ".env").write_text("ADMIN_BOT_TOKEN=" + fake_token, encoding="utf-8")
        (self.root / "runtime").mkdir(); (self.root / "runtime" / "secret.session").write_text("SECRET", encoding="utf-8")
        (log_dir / "service.log").write_text(f"phone {fake_phone} token {fake_token}", encoding="utf-8")
        settings = SimpleNamespace(
            diagnostics_dir=diag_dir,
            log_dir=log_dir,
            backup_dir=backup_dir,
            media_cache_dir=cache_dir,
            heartbeat_stale_seconds=180,
            ensure_dirs=lambda: None,
        )
        zpath = generate_diagnostics(self.db, settings)
        with zipfile.ZipFile(zpath) as z:
            names = set(z.namelist())
            self.assertNotIn(".env", names)
            self.assertFalse(any(x.endswith(".session") for x in names))
            self.assertIn("system_status.json", names)
            log = z.read("logs/service.log").decode()
            self.assertNotIn(fake_phone, log)
            self.assertNotIn("AAFake", log)

    def test_admin_dashboard_and_allowlist(self):
        safety = SafetyController(self.db)
        settings = SimpleNamespace(admin_user_ids=(123,), max_queue_size=100, max_pending_per_campaign=50, max_pending_per_destination=10)
        controller = TelegramAdminController(self.db, settings, safety)
        self.assertTrue(controller.authorized(123))
        self.assertFalse(controller.authorized(999))
        self.assertIn(f"SMART AUTO POSTER V{__version__}", dashboard_text(self.db))
        self.assertIn("Primary", accounts_text(self.db))
        self.assertIn("ad_a", content_text(self.db))

    def test_destination_search(self):
        text = search_destinations_text(self.db, "Main")
        self.assertIn("Main Destination", text)
        self.assertIn("-1001", text)

    def test_once_schedule_disables_after_run(self):
        self._preview_activate()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="minutes")
        configure_once(self.db, "camp", future, "Australia/Adelaide")
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds")
        with self.db.connect() as con:
            con.execute("UPDATE campaign_schedules SET next_run_at=? WHERE campaign_id='camp'", (past,))
        Scheduler(self.db).tick()
        with self.db.connect() as con:
            row = con.execute("SELECT enabled,next_run_at FROM campaign_schedules WHERE campaign_id='camp'").fetchone()
            q = con.execute("SELECT COUNT(*) FROM queue WHERE campaign_id='camp'").fetchone()[0]
        self.assertEqual(row["enabled"], 0)
        self.assertIsNone(row["next_run_at"])
        self.assertEqual(q, 1)

    def test_spread_window_is_deterministic_and_bounded(self):
        # Freeze the scheduler reference clock so this test verifies deterministic
        # spread offset rather than depending on how long two enqueue calls take
        # on the host OS. The previous test could cross a one-second boundary on
        # Windows and fail even though the spread algorithm itself was stable.
        fixed_now = "2026-08-28T16:00:00+00:00"
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET spread_seconds=1800 WHERE campaign_id='camp'")
        self._preview_activate()
        with patch("smart_autoposter.core.utcnow", return_value=fixed_now):
            result = enqueue_campaign(self.db, "camp", run_key="spread")
        due = datetime.fromisoformat(result["first_due_at"])
        base = datetime.fromisoformat(fixed_now)
        self.assertGreaterEqual((due - base).total_seconds(), 0)
        self.assertLessEqual((due - base).total_seconds(), 1800)
        with self.db.connect() as con:
            first = con.execute("SELECT due_at FROM queue").fetchone()[0]
            con.execute("DELETE FROM queue")
        with patch("smart_autoposter.core.utcnow", return_value=fixed_now):
            result2 = enqueue_campaign(self.db, "camp", run_key="spread")
        self.assertEqual(first, result2["first_due_at"])

    def test_cross_campaign_gap(self):
        create_content(self.db, "ad_b", "Caption B", [])
        create_campaign(self.db, "other", "Other", "ad_b", tags="main")
        mark_campaign_previewed(self.db, "other"); set_campaign_state(self.db, "other", "active")
        enqueue_campaign(self.db, "other", run_key="other")
        with self.db.connect() as con:
            other = con.execute("SELECT id,due_at FROM queue WHERE campaign_id='other'").fetchone()
            con.execute("UPDATE queue SET status='sent',resolved_at=?,updated_at=? WHERE id=?", (other["due_at"], other["due_at"], other["id"]))
        set_campaign_gap(self.db, "camp", "other", 90)
        self._preview_activate()
        enqueue_campaign(self.db, "camp", run_key="camp")
        with self.db.connect() as con:
            rows = {r["campaign_id"]: datetime.fromisoformat(r["due_at"]) for r in con.execute("SELECT campaign_id,due_at FROM queue")}
        self.assertGreaterEqual((rows["camp"] - rows["other"]).total_seconds(), 90 * 60)

    def test_templates_create_campaign(self):
        keys = {x["key"] for x in list_templates()}
        self.assertIn("rotating_ads", keys)
        create_from_template(self.db, "announcement", "announce", "Announcement", "ad_a", tags="main")
        with self.db.connect() as con:
            row = con.execute("SELECT priority,lifecycle_state FROM campaigns WHERE campaign_id='announce'").fetchone()
        self.assertEqual(row["priority"], 90)
        self.assertEqual(row["lifecycle_state"], "draft")

    def test_analytics_snapshot(self):
        self._enqueue()
        with self.db.connect() as con:
            con.execute("UPDATE queue SET status='sent',account_key='primary',updated_at=?", (utcnow(),))
        data = analytics_snapshot(self.db, 24)
        self.assertEqual(data["campaigns"][0]["sent"], 1)
        self.assertEqual(data["accounts"][0]["account_key"], "primary")


if __name__ == "__main__":
    unittest.main()
