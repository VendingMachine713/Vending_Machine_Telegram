from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from smart_autoposter.admin_bot import authorized
from smart_autoposter.analytics import analytics_snapshot
from smart_autoposter.core import (
    add_campaign_content,
    campaign_preview,
    clone_campaign,
    create_campaign,
    create_content,
    enqueue_campaign,
    validate,
)
from smart_autoposter.db import Database, utcnow
from smart_autoposter.inbox import import_content_inbox
from smart_autoposter.notifications import NotificationQueue
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
from smart_autoposter.scheduler import Scheduler, configure_interval, configure_once, schedule_occurrences
from smart_autoposter.watchdog import watchdog_status


class V24AutonomousTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "data" / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,updated_at) VALUES('primary','p',1,1,'p',?)", (now,))
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,updated_at) VALUES('secondary','s',1,1,'s',?)", (now,))
            con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'Group',1,1,'both','text',1,0,?)", (now,))
            con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(-1001,'main')")
        create_content(self.db, "ad_a", "Caption A", [])
        create_campaign(self.db, "camp", "Campaign", "ad_a", tags="main")

    def tearDown(self):
        self.tmp.cleanup()

    def _preview_activate(self):
        campaign_preview(self.db, "camp")
        mark_campaign_previewed(self.db, "camp")
        set_campaign_state(self.db, "camp", "active")

    def _enqueue(self, run_key="run"):
        self._preview_activate()
        return enqueue_campaign(self.db, "camp", run_key=run_key)

    def test_activation_requires_preview(self):
        with self.assertRaisesRegex(RuntimeError, "Preview"):
            set_campaign_state(self.db, "camp", "active")

    def test_preview_moves_draft_to_ready(self):
        mark_campaign_previewed(self.db, "camp")
        with self.db.connect() as con:
            row = con.execute("SELECT lifecycle_state,last_preview_at FROM campaigns WHERE campaign_id='camp'").fetchone()
        self.assertEqual(row["lifecycle_state"], "ready")
        self.assertTrue(row["last_preview_at"])

    def test_activation_after_preview(self):
        mark_campaign_previewed(self.db, "camp")
        result = set_campaign_state(self.db, "camp", "active")
        self.assertEqual(result["state"], "active")
        self.assertTrue(result["enabled"])

    def test_archive_disables_schedule(self):
        self._preview_activate()
        configure_interval(self.db, "camp", 3600, "Australia/Adelaide")
        set_campaign_state(self.db, "camp", "archived")
        with self.db.connect() as con:
            sched = con.execute("SELECT enabled FROM campaign_schedules WHERE campaign_id='camp'").fetchone()
        self.assertEqual(sched["enabled"], 0)

    def test_content_disable_blocked_when_active(self):
        self._preview_activate()
        with self.assertRaisesRegex(RuntimeError, "active campaign"):
            set_content_state(self.db, "ad_a", "disabled")

    def test_content_tags_add_and_remove(self):
        self.assertEqual(set_content_tags(self.db, "ad_a", add=["sale", "new"]), ["new", "sale"])
        self.assertEqual(set_content_tags(self.db, "ad_a", remove=["new"]), ["sale"])

    def test_destination_search(self):
        from smart_autoposter.operations import search_destinations
        rows = search_destinations(self.db, "Group")
        self.assertEqual(len(rows), 1)

    def test_bulk_destination_protect_and_never(self):
        n = bulk_destination_action(self.db, tag="main", protect=True, never_auto_post=True)
        self.assertEqual(n, 1)
        with self.db.connect() as con:
            row = con.execute("SELECT protected,never_auto_post,enabled FROM destinations WHERE group_id=-1001").fetchone()
        self.assertEqual((row["protected"], row["never_auto_post"], row["enabled"]), (1, 1, 0))

    def test_redaction(self):
        value = "token 123456789:AAabcdefghijklmnop hash 0123456789abcdef0123456789abcdef phone +61412345678"
        safe = redact_text(value)
        self.assertNotIn("123456789:AA", safe)
        self.assertNotIn("0123456789abcdef0123456789abcdef", safe)
        self.assertNotIn("+61412345678", safe)

    def test_diagnostics_excludes_secrets_and_redacts_logs(self):
        from smart_autoposter.diagnostics import build_support_bundle
        log = self.root / "logs" / "app.log"; log.parent.mkdir(); log.write_text("phone +61412345678", encoding="utf-8")
        secret = self.root / ".env"; secret.write_text("ADMIN_BOT_TOKEN=secret", encoding="utf-8")
        bundle = build_support_bundle(self.root, self.db, include_logs=True)
        names = [p.name for p in bundle.iterdir()]
        self.assertNotIn(".env", names)
        text = (bundle / "logs" / "app.log").read_text(encoding="utf-8")
        self.assertNotIn("+61412345678", text)

    def test_duplicate_content_fingerprint_rejected(self):
        create_content(self.db, "dup1", "Same", [])
        with self.assertRaisesRegex(RuntimeError, "Duplicate content fingerprint"):
            create_content(self.db, "dup2", "Same", [])

    def test_content_inbox_duplicate_is_rejected(self):
        inbox = self.root / "inbox"; inbox.mkdir()
        folder = inbox / "ad"; folder.mkdir(); (folder / "caption.txt").write_text("Inbox", encoding="utf-8")
        first = import_content_inbox(self.db, inbox)
        self.assertEqual(first["imported"], 1)
        second = import_content_inbox(self.db, inbox)
        self.assertEqual(second["duplicates"], 1)

    def test_notification_dedupe(self):
        q = NotificationQueue(self.db)
        a = q.enqueue("WARNING", "T", "M", dedupe_key="x", dedupe_window_seconds=60)
        b = q.enqueue("WARNING", "T", "M", dedupe_key="x", dedupe_window_seconds=60)
        self.assertEqual(a, b)
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 1)

    def test_notification_dedupe_window_requeues_old(self):
        q = NotificationQueue(self.db)
        a = q.enqueue("WARNING", "T", "M", dedupe_key="x", dedupe_window_seconds=1)
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
        with self.db.connect() as con:
            con.execute("UPDATE notifications SET created_at=?,status='sent' WHERE id=?", (old, a))
        b = q.enqueue("WARNING", "T2", "M2", dedupe_key="x", dedupe_window_seconds=1)
        self.assertEqual(a, b)
        with self.db.connect() as con:
            row = con.execute("SELECT title,status FROM notifications WHERE id=?", (a,)).fetchone()
        self.assertEqual(row["title"], "T2")
        self.assertEqual(row["status"], "pending")

    def test_notification_severity_filter(self):
        q = NotificationQueue(self.db)
        q.enqueue("INFO", "I", "I")
        q.enqueue("ERROR", "E", "E")
        self.assertEqual(len(q.pending(min_severity="WARNING")), 1)

    def test_watchdog_detects_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(timespec="seconds")
        with self.db.connect() as con:
            con.execute("INSERT INTO heartbeats(component,last_seen_at,status) VALUES('worker',?,'ok')", (old,))
        result = watchdog_status(self.db, stale_seconds=60)
        self.assertFalse(result["healthy"])

    def test_analytics_snapshot(self):
        self._enqueue("analytics")
        snap = analytics_snapshot(self.db)
        self.assertIn("queue", snap)
        self.assertEqual(snap["queue"].get("pending"), 1)

    def test_admin_dashboard_and_allowlist(self):
        self.assertTrue(authorized(123, {123}))
        self.assertFalse(authorized(999, {123}))

    def test_queue_total_capacity_guard(self):
        self._preview_activate()
        with self.assertRaisesRegex(RuntimeError, "MAX_QUEUE_SIZE"):
            enforce_queue_limits(
                self.db,
                add_count=1,
                campaign_id="camp",
                group_ids=[-1001],
                max_queue_size=0,
                max_pending_per_campaign=100,
                max_pending_per_destination=100,
            )

    def test_queue_campaign_capacity_guard(self):
        self._enqueue("cap")
        with self.assertRaisesRegex(RuntimeError, "MAX_PENDING_PER_CAMPAIGN"):
            enforce_queue_limits(
                self.db,
                add_count=1,
                campaign_id="camp",
                group_ids=[-1001],
                max_queue_size=100,
                max_pending_per_campaign=1,
                max_pending_per_destination=100,
            )

    def test_queue_destination_capacity_guard(self):
        self._enqueue("destcap")
        with self.assertRaisesRegex(RuntimeError, "MAX_PENDING_PER_DESTINATION"):
            enforce_queue_limits(
                self.db,
                add_count=1,
                campaign_id="camp",
                group_ids=[-1001],
                max_queue_size=100,
                max_pending_per_campaign=100,
                max_pending_per_destination=1,
            )

    def test_job_defer_cancel_retry(self):
        self._enqueue("jobs")
        with self.db.connect() as con:
            jid = con.execute("SELECT id FROM queue").fetchone()[0]
        row = manage_job(self.db, jid, "defer", minutes=5)
        self.assertEqual(row["status"], "deferred")
        row = manage_job(self.db, jid, "cancel")
        self.assertEqual(row["status"], "cancelled")
        row = manage_job(self.db, jid, "retry")
        self.assertEqual(row["status"], "retry")

    def test_schema_v5_has_autonomous_tables(self):
        with self.db.connect() as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"notifications", "heartbeats", "audit_log"}.issubset(tables))

    def test_once_schedule_disables_after_run(self):
        self._preview_activate()
        future = datetime.now(timezone.utc) + timedelta(seconds=2)
        configure_once(self.db, "camp", future.isoformat(), "Australia/Adelaide")
        with self.db.connect() as con:
            con.execute("UPDATE campaign_schedules SET next_run_at=? WHERE campaign_id='camp'", ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(timespec="seconds"),))
        Scheduler(self.db).tick()
        with self.db.connect() as con:
            row = con.execute("SELECT enabled,next_run_at FROM campaign_schedules WHERE campaign_id='camp'").fetchone()
            q = con.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
        self.assertEqual(row["enabled"], 0)
        self.assertIsNone(row["next_run_at"])
        self.assertEqual(q, 1)

    def test_spread_window_is_deterministic_and_bounded(self):
        # Freeze the scheduler reference clock so this test verifies deterministic
        # spread offset rather than depending on how long two enqueue calls take.
        # The second reconstruction explicitly removes the test-only run seal: in
        # production, deleting queue rows must NOT make a sealed run replayable.
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
            con.execute("DELETE FROM queue_run_seals WHERE campaign_id='camp' AND run_key='spread'")
        with patch("smart_autoposter.core.utcnow", return_value=fixed_now):
            result2 = enqueue_campaign(self.db, "camp", run_key="spread")
        self.assertEqual(first, result2["first_due_at"])

    def test_cross_campaign_gap(self):
        create_content(self.db, "ad_b", "Caption B", [])
        create_campaign(self.db, "other", "Other", "ad_b", tags="main")
        mark_campaign_previewed(self.db, "other"); set_campaign_state(self.db, "other", "active")
        enqueue_campaign(self.db, "other", run_key="other")
        set_campaign_gap(self.db, "camp", "other", 90)
        result = enqueue_campaign(self.db, "camp", run_key="gap")
        with self.db.connect() as con:
            rows = con.execute("SELECT campaign_id,due_at FROM queue ORDER BY id").fetchall()
        due_other = datetime.fromisoformat(rows[0]["due_at"])
        due_camp = datetime.fromisoformat(rows[1]["due_at"])
        self.assertGreaterEqual((due_camp - due_other).total_seconds(), 90*60)

    def test_templates_create_campaign(self):
        from smart_autoposter.templates import create_from_template
        create_from_template(self.db, "standard", "templ", "Templ", "ad_a", tags="main")
        with self.db.connect() as con:
            row = con.execute("SELECT lifecycle_state,enabled FROM campaigns WHERE campaign_id='templ'").fetchone()
        self.assertEqual(row["lifecycle_state"], "draft")
        self.assertEqual(row["enabled"], 0)

    def test_schedule_simulation_does_not_enqueue(self):
        self._preview_activate()
        configure_interval(self.db, "camp", 3600, "Australia/Adelaide")
        with self.db.connect() as con:
            row = dict(con.execute("SELECT * FROM campaign_schedules WHERE campaign_id='camp'").fetchone())
        start = datetime.now(timezone.utc)
        end = start + timedelta(hours=4)
        occurrences = schedule_occurrences(row, start, end)
        self.assertGreaterEqual(len(occurrences), 1)
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM queue").fetchone()[0], 0)

    def test_database_integrity(self):
        self.assertEqual(validate(self.db), [])


if __name__ == "__main__":
    unittest.main()
