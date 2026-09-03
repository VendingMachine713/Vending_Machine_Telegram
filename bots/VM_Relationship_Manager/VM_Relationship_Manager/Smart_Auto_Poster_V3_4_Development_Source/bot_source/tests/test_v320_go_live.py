import contextlib
import io
import json
import os
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from smart_autoposter.cli import cmd_go_live_readiness
from smart_autoposter.collections import CollectionSpec, upsert_collection
from smart_autoposter.core import create_content
from smart_autoposter.db import Database, utcnow
from smart_autoposter.production import (
    ProductionBootstrapSpec,
    bootstrap_production,
    reconcile_visual_canary_sent,
)
from smart_autoposter.scheduler import configure_interval, rearm_schedule
from smart_autoposter import settings as settings_module


class V320GoLiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_cwd = Path.cwd()
        os.chdir(self.root)
        self.db_path = self.root / "data" / "test.sqlite3"
        self.db = Database(self.db_path)
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at)
                   VALUES(-1001,'Production',1,0,'primary','photo',1,0,?)""",
                (now,),
            )
            con.execute(
                """INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at)
                   VALUES(-1002,'Canary',1,0,'primary','text',1,0,?)""",
                (now,),
            )
            con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(-1002,'live_test')")
        upsert_collection(self.db, CollectionSpec("all_approved", "All Approved", exclude_tags="live_test"))
        upsert_collection(self.db, CollectionSpec("live_test", "Live Test", include_tags="live_test", required_access="primary", mode="text"))

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def _content(self, content_id="main_ad_01_fixed", count=10):
        folder = self.root / "content" / "library" / content_id
        folder.mkdir(parents=True, exist_ok=True)
        media = []
        for i in range(count):
            p = folder / f"{i+1:02}.jpg"
            p.write_bytes(f"{content_id}-{i}".encode())
            media.append(str(p.relative_to(self.root)))
        (folder / "caption.txt").write_text("caption", encoding="utf-8")
        create_content(self.db, content_id, "caption", media, source_dir=str(folder.relative_to(self.root)))

    def _ready_with_visual_receipt(self):
        self._content()
        result = bootstrap_production(
            self.db,
            "Australia/Adelaide",
            ProductionBootstrapSpec(
                explicit_content_ids=("main_ad_01_fixed",),
                interval_minutes=240,
            ),
        )
        gid = result["canary"]["destination_id"]
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,max_attempts,error_kind,last_error,created_at,updated_at)
                   VALUES('go-live-canary','approved','album_canary_01',?,'main_ad_01_fixed',?,'retry',1,4,'slow_mode','ambiguous',?,?)""",
                (gid, now, now, now),
            )
            job_id = int(con.execute("SELECT MAX(id) FROM queue").fetchone()[0])
        reconcile_visual_canary_sent(
            self.db,
            job_id=job_id,
            confirmation="ALBUM_VISUALLY_CONFIRMED_SENT",
        )
        receipt = self.root / "runtime" / "canary" / "album_canary_visual_ok.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps({
                "job_id": job_id,
                "confirmation": "ALBUM_OK",
                "telegram_send_performed": False,
            }),
            encoding="utf-8",
        )
        return job_id, receipt


    def test_v321_defaults_main_production_to_four_hours(self):
        self.assertEqual(ProductionBootstrapSpec().interval_minutes, 240)
        root = Path(__file__).parents[1]
        go_live = (root / "GO_LIVE.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$IntervalMinutes = 240", go_live)
        self.assertIn("--interval-minutes $IntervalMinutes --start-in-minutes $IntervalMinutes", go_live)
        schedule_pos = go_live.index("--interval-minutes $IntervalMinutes --start-in-minutes $IntervalMinutes")
        strict_pos = go_live.index("Write-Host '> Strict local readiness...'")
        self.assertLess(schedule_pos, strict_pos)
        activate = (root / "ACTIVATE_MAIN_PRODUCTION.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("--interval-minutes 240 --start-in-minutes 240", activate)
        self.assertLess(activate.index("--interval-minutes 240"), activate.index("go-live-readiness"))

    def test_rearm_interval_resets_stale_slot_to_full_interval(self):
        self._content()
        bootstrap_production(
            self.db,
            "Australia/Adelaide",
            ProductionBootstrapSpec(explicit_content_ids=("main_ad_01_fixed",), configure_canary=False, interval_minutes=240),
        )
        reference = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        with self.db.connect() as con:
            con.execute(
                "UPDATE campaign_schedules SET next_run_at=? WHERE campaign_id='main_production_01'",
                ((reference - timedelta(days=3)).isoformat(timespec="seconds"),),
            )
        out = rearm_schedule(self.db, "main_production_01", after_utc=reference)
        self.assertEqual(
            out["next_run_at"],
            (reference + timedelta(hours=4)).isoformat(timespec="seconds"),
        )
        with self.db.connect() as con:
            row = con.execute("SELECT next_run_at,last_run_at FROM campaign_schedules WHERE campaign_id='main_production_01'").fetchone()
        self.assertEqual(row[0], out["next_run_at"])
        self.assertIsNone(row[1])

    def test_go_live_readiness_accepts_clean_inactive_album_state(self):
        job_id, receipt = self._ready_with_visual_receipt()
        args = Namespace(
            campaign_id="main_production_01",
            collection="all_approved",
            canary_campaign="album_canary_01",
            visual_receipt=str(receipt),
            expected_destinations=1,
            expected_variants=1,
            require_album_items=10,
            expected_interval_minutes=240,
            require_admin_bot=False,
        )
        env = {
            "SMART_AUTOPOSTER_DISABLE_DOTENV": "1",
            "DATABASE_PATH": str(self.db_path),
            "CONTENT_ROOT": str(self.root / "content"),
            "RUNTIME_LOCK_PATH": str(self.root / "runtime" / "lock"),
            "BACKUP_DIR": str(self.root / "backups"),
            "LOG_DIR": str(self.root / "logs"),
            "MEDIA_CACHE_DIR": str(self.root / "cache"),
            "CONFIG_CSV": str(self.root / "config.csv"),
        }
        buf = io.StringIO()
        with patch.dict(os.environ, env, clear=False), contextlib.redirect_stdout(buf):
            cmd_go_live_readiness(args)
        out = json.loads(buf.getvalue())
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["canary"]["id"], job_id)
        self.assertEqual(out["global_unresolved_queue"], [])
        self.assertEqual(out["production"]["media_delivery"]["text_destinations"], 0)

    def test_go_live_readiness_blocks_any_unresolved_queue_job(self):
        _job_id, receipt = self._ready_with_visual_receipt()
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO queue(job_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at)
                   VALUES('unexpected','main_production_01',-1001,'main_ad_01_fixed',?,'pending',?,?)""",
                (now, now, now),
            )
        args = Namespace(
            campaign_id="main_production_01",
            collection="all_approved",
            canary_campaign="album_canary_01",
            visual_receipt=str(receipt),
            expected_destinations=1,
            expected_variants=1,
            require_album_items=10,
            expected_interval_minutes=240,
            require_admin_bot=False,
        )
        env = {
            "SMART_AUTOPOSTER_DISABLE_DOTENV": "1",
            "DATABASE_PATH": str(self.db_path),
            "CONTENT_ROOT": str(self.root / "content"),
        }
        with patch.dict(os.environ, env, clear=False), self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_go_live_readiness(args)

    def test_settings_test_mode_prevents_project_dotenv_override(self):
        fake_env = self.root / "production.env"
        fake_env.write_text(
            "DATABASE_PATH=SHOULD_NOT_OVERRIDE_TEST.sqlite3\nCONTENT_ROOT=SHOULD_NOT_OVERRIDE_CONTENT\n",
            encoding="utf-8",
        )
        expected_db = self.root / "data" / "isolated.sqlite3"
        expected_content = self.root / "isolated-content"
        with patch.object(settings_module, "PROJECT_ENV_PATH", fake_env), patch.dict(
            os.environ,
            {
                "SMART_AUTOPOSTER_DISABLE_DOTENV": "1",
                "DATABASE_PATH": str(expected_db),
                "CONTENT_ROOT": str(expected_content),
            },
            clear=False,
        ):
            loaded = settings_module.Settings.load(False)
        self.assertEqual(loaded.database_path, expected_db)
        self.assertEqual(loaded.content_root, expected_content)

    def test_final_go_live_script_is_fail_closed_and_has_no_post_now(self):
        root = Path(__file__).parents[1]
        text = (root / "GO_LIVE.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("ACTIVATE_32_ALBUM_PRODUCTION_4H", text)
        self.assertIn("go-live-readiness", text)
        self.assertIn("accounts-check", text)
        self.assertIn("admin-probe", text)
        self.assertIn("schedule-rearm", text)
        self.assertLess(text.index("schedule-rearm"), text.index("campaign-state $Campaign active"))
        self.assertIn("New-LocalDbSnapshot", text)
        self.assertIn("Restore-DbSnapshot", text)
        self.assertIn("TaskExistedBefore", text)
        self.assertIn("Unregister-ScheduledTask", text)
        self.assertIn("Start-ScheduledTask", text)
        self.assertIn("watchdog --require service --require scheduler --require worker --require admin_bot", text)
        self.assertIn("Immediate Post Now: NONE", text)
        self.assertNotIn("post-now", text.lower().replace("immediate post now", ""))
        self.assertIn("AddSeconds(75)", text)
        self.assertIn("Service/Admin Bot watchdog did not become healthy within 75 seconds", text)
        self.assertIn("Get-Content $serviceLog.FullName -Tail 40", text)
        self.assertIn("$HeartbeatMaxAgeSeconds = @{ service = 20; scheduler = 45; worker = 20; admin_bot = 20 }", text)
        self.assertIn("$maxAge = [double]$HeartbeatMaxAgeSeconds[$component]", text)
        self.assertIn("$taskState -eq 'Running'", text)
        self.assertIn("Managed-service stability recheck", text)

    def test_v324_scheduler_stability_budget_allows_normal_tick_jitter(self):
        root = Path(__file__).parents[1]
        text = (root / "GO_LIVE.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("scheduler = 45", text)
        self.assertIn("service = 20", text)
        self.assertIn("worker = 20", text)
        self.assertIn("admin_bot = 20", text)
        self.assertIn("Clear-StaleRuntimeLockSafely", text)
        self.assertIn("Runtime lock owner is still alive; lock was not removed.", text)

    def test_v325_verified_live_lock_owner_cleanup_is_pid_reuse_safe(self):
        root = Path(__file__).parents[1]
        text = (root / "GO_LIVE.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Stop-VerifiedRuntimeLockOwnerSafely", text)
        self.assertIn("[DateTimeOffset]::Parse([string]$owner.started_at)", text)
        self.assertIn("(Get-Process -Id $ownerPid -ErrorAction Stop).StartTime", text)
        self.assertIn("if ($delta -gt 120)", text)
        self.assertIn("Stop-Process -Id $ownerPid -Force", text)
        self.assertIn("PID has almost certainly been reused", text)
        self.assertLess(text.index("Stop-ServiceTaskSafely"), text.index("Clear-StaleRuntimeLockSafely"))

    def test_v326_normalizes_orphan_active_before_snapshot(self):
        root = Path(__file__).parents[1]
        text = (root / "GO_LIVE.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Normalize-OrphanedActiveProduction", text)
        self.assertIn("Orphaned ACTIVE production detected with zero unresolved jobs", text)
        self.assertIn("ACTIVE production cannot be normalized because additional go-live safety problems exist", text)
        self.assertIn("ACTIVE production has unresolved queue work", text)
        call = "$NormalizedForGoLive = Normalize-OrphanedActiveProduction"
        snapshot = "$DbSnapshot = New-LocalDbSnapshot"
        self.assertLess(text.index(call), text.index(snapshot))

    def test_v326_failed_go_live_verifies_ready_after_restore(self):
        root = Path(__file__).parents[1]
        text = (root / "GO_LIVE.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Ensure-FailedGoLiveInactive", text)
        restore = "Restore-DbSnapshot $DbSnapshot"
        verify = "try { Ensure-FailedGoLiveInactive }"
        self.assertLess(text.rindex(restore), text.rindex(verify))
        self.assertIn("Rollback verification failed: production is not READY/inactive", text)
        self.assertIn("production rollback verified READY/inactive", text)


if __name__ == "__main__":
    unittest.main()
