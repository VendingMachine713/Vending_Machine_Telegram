import json
import os
import tempfile
import unittest
from pathlib import Path

from smart_autoposter.collections import CollectionSpec, upsert_collection
from smart_autoposter.content_library import import_content_inbox, audit_content_library
from smart_autoposter.core import create_campaign, create_content
from smart_autoposter.db import Database, utcnow
from smart_autoposter.operations import set_content_state
from smart_autoposter.production import ProductionBootstrapSpec, bootstrap_production, production_readiness, canary_queue_status, album_delivery_plan, apply_album_delivery_modes, reconcile_visual_canary_sent
from smart_autoposter.scheduler import simulate_schedules
from smart_autoposter.telegram_io import TelegramPool
from smart_autoposter.wizard import _ask_choice, _parse_content_selection
from unittest.mock import patch


class V305ProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_cwd = Path.cwd()
        os.chdir(self.root)
        self.db = Database(self.root / "data" / "test.sqlite3")
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

    def _content(self, content_id: str, caption: str, media_count: int = 2):
        folder = self.root / "content" / "library" / content_id
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in range(media_count):
            p = folder / f"{i+1:02}.jpg"
            p.write_bytes((content_id + str(i)).encode())
            paths.append(str(p.relative_to(self.root)))
        (folder / "caption.txt").write_text(caption, encoding="utf-8")
        create_content(self.db, content_id, caption, paths, source_dir=str(folder.relative_to(self.root)))

    def test_importer_normalizes_numbered_caption_filename(self):
        inbox = self.root / "content" / "inbox" / "Main Ad 02"
        inbox.mkdir(parents=True)
        (inbox / "Caption_02.txt").write_text("Unique caption", encoding="utf-8")
        (inbox / "01.jpg").write_bytes(b"img")
        result = import_content_inbox(self.db, self.root / "content")
        self.assertEqual(result[0]["status"], "ready")
        self.assertEqual(result[0]["caption_source"], "Caption_02.txt")
        self.assertIn("normalized", result[0]["caption_note"])
        self.assertTrue((self.root / "content" / "library" / "main_ad_02" / "caption.txt").exists())
        with self.db.connect() as con:
            row = con.execute("SELECT caption FROM content WHERE content_id='main_ad_02'").fetchone()
        self.assertEqual(row[0], "Unique caption")

    def test_importer_rejects_ambiguous_caption_candidates(self):
        inbox = self.root / "content" / "inbox" / "Ambiguous"
        inbox.mkdir(parents=True)
        (inbox / "Caption_01.txt").write_text("A", encoding="utf-8")
        (inbox / "caption-main.txt").write_text("B", encoding="utf-8")
        result = import_content_inbox(self.db, self.root / "content")
        self.assertEqual(result[0]["status"], "rejected")
        self.assertIn("multiple caption candidates", result[0]["reason"])

    def test_bootstrap_builds_ready_inactive_campaign_and_album_canary(self):
        self._content("main_ad_01", "Broken old", 2)
        set_content_state(self.db, "main_ad_01", "disabled")
        for i in range(2, 6):
            self._content(f"main_ad_0{i}", f"Caption {i}", 2)
        self._content("main_ad_01_fixed", "Caption 1", 2)
        create_campaign(self.db, "live_test_001", "Legacy", "main_ad_01_fixed")
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active' WHERE campaign_id='live_test_001'")

        result = bootstrap_production(self.db, "Australia/Adelaide", ProductionBootstrapSpec())
        self.assertEqual(result["state"], "ready")
        self.assertFalse(result["send_performed"])
        self.assertEqual(result["content_count"], 5)
        self.assertEqual(result["preview"]["selected"], 1)
        self.assertEqual(result["preview"]["collections"], ["all_approved"])
        self.assertTrue(result["canary"]["configured"])
        self.assertEqual(result["canary"]["preview"]["selected"], 1)
        with self.db.connect() as con:
            camp = con.execute("SELECT enabled,lifecycle_state,rotation_mode,exclude_tags FROM campaigns WHERE campaign_id='main_production_01'").fetchone()
            canary_mode = con.execute("SELECT mode FROM destinations WHERE group_id=-1002").fetchone()[0]
            legacy = con.execute("SELECT lifecycle_state,enabled FROM campaigns WHERE campaign_id='live_test_001'").fetchone()
            queue_count = con.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
        self.assertEqual(tuple(camp[:3]), (0, "ready", "least_recent"))
        self.assertIn("live_test", camp[3])
        self.assertEqual(canary_mode, "photo")
        self.assertEqual(tuple(legacy), ("paused", 0))
        self.assertEqual(queue_count, 0)

    def test_bootstrap_repairs_legacy_text_only_live_test_collection_for_album_canary(self):
        self._content("main_ad_01_fixed", "Caption 1", 10)
        result = bootstrap_production(self.db, "Australia/Adelaide", ProductionBootstrapSpec())
        self.assertTrue(result["canary"]["configured"])
        self.assertEqual(result["canary"]["collection_mode_before"], "text")
        self.assertEqual(result["canary"]["collection_mode_after"], "photo")
        self.assertEqual(result["canary"]["preview"]["selected"], 1)
        self.assertEqual(result["canary"]["destination_id"], -1002)
        self.assertEqual(result["canary"]["preview"]["selected"], 1)
        with self.db.connect() as con:
            collection_mode = con.execute("SELECT mode FROM destination_collections WHERE collection_id='live_test'").fetchone()[0]
            destination_mode = con.execute("SELECT mode FROM destinations WHERE group_id=-1002").fetchone()[0]
            queue_count = con.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
        self.assertEqual(collection_mode, "photo")
        self.assertEqual(destination_mode, "photo")
        self.assertEqual(queue_count, 0)

    def test_readiness_and_inactive_simulation_work_before_activation(self):
        for i in range(1, 3):
            self._content(f"main_ad_0{i}", f"Caption {i}", 2)
        result = bootstrap_production(
            self.db,
            "Australia/Adelaide",
            ProductionBootstrapSpec(configure_canary=False, interval_minutes=60),
        )
        ready = production_readiness(self.db, "main_production_01", expected_collection="all_approved")
        self.assertTrue(ready["ok"], ready)
        self.assertEqual(ready["state"], "ready")
        rows = simulate_schedules(self.db, 3, include_inactive=True, campaign_id="main_production_01")
        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(all(r["lifecycle_state"] == "ready" for r in rows))
        active_only = simulate_schedules(self.db, 3, campaign_id="main_production_01")
        self.assertEqual(active_only, [])
        self.assertGreaterEqual(len(result["simulation_24h"]), 1)


    def test_content_audit_flags_enabled_blank_caption_but_not_as_hard_failure(self):
        self._content("main_ad_01", "", 2)
        result = audit_content_library(self.db, self.root / "content")
        self.assertTrue(result["ok"])
        self.assertTrue(any("empty caption" in x for x in result["warnings"]))

    def test_content_selection_accepts_numbers_and_exact_ids(self):
        rows = [
            {"content_id": "alpha"},
            {"content_id": "beta"},
            {"content_id": "gamma"},
        ]
        self.assertEqual(_parse_content_selection("1,gamma,2", rows), ["alpha", "gamma", "beta"])

    def test_choice_normalizes_display_label_and_lru_alias(self):
        with patch("builtins.input", return_value="Mode: any"):
            self.assertEqual(_ask_choice("Mode", {"any", "photo", "text"}, "any"), "any")
        with patch("builtins.input", return_value="lru"):
            self.assertEqual(
                _ask_choice("Rotation", {"sequential", "least_recent"}, "sequential", aliases={"lru": "least_recent"}),
                "least_recent",
            )



    def test_canary_status_reports_existing_retry_without_enqueuing(self):
        self._content("main_ad_01_fixed", "Caption 1", 10)
        result = bootstrap_production(self.db, "Australia/Adelaide", ProductionBootstrapSpec())
        gid = result["canary"]["destination_id"]
        due = "2099-01-01T00:00:00+00:00"
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,max_attempts,error_kind,last_error,created_at,updated_at)
                   VALUES('canary-existing','approved','album_canary_01',?,'main_ad_01_fixed',?,'retry',1,4,'slow_mode','slow_mode test',?,?)""",
                (gid,due,now,now),
            )
            before = con.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
        status = canary_queue_status(self.db)
        with self.db.connect() as con:
            after = con.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
        self.assertEqual(status["status"], "retry")
        self.assertTrue(status["resume_required"])
        self.assertGreater(status["seconds_until_due"], 0)
        self.assertEqual(before, after)

    def test_readiness_warns_when_album_campaign_includes_text_mode_destinations(self):
        # all_approved includes the production photo destination and a second
        # production text destination; LIVE_TEST remains excluded.
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at)
                   VALUES(-1003,'Production Text',1,0,'primary','text',1,0,?)""",
                (now,),
            )
        self._content("main_ad_01_fixed", "Caption 1", 10)
        bootstrap_production(self.db, "Australia/Adelaide", ProductionBootstrapSpec(configure_canary=False))
        ready = production_readiness(self.db, "main_production_01", expected_collection="all_approved")
        self.assertTrue(ready["ok"])
        self.assertEqual(ready["media_delivery"]["photo_destinations"], 1)
        self.assertEqual(ready["media_delivery"]["text_destinations"], 1)
        self.assertTrue(ready["media_delivery"]["text_destinations_receive_caption_only"])
        self.assertTrue(any("caption-only" in warning for warning in ready["warnings"]))



    def test_visual_reconcile_resolves_latest_retry_canary_without_send(self):
        self._content("main_ad_01_fixed", "Caption 1", 10)
        result = bootstrap_production(self.db, "Australia/Adelaide", ProductionBootstrapSpec())
        gid = result["canary"]["destination_id"]
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,max_attempts,error_kind,last_error,created_at,updated_at)
                   VALUES('canary-visual','approved','album_canary_01',?,'main_ad_01_fixed',?,'retry',1,4,'slow_mode','ambiguous acknowledgement',?,?)""",
                (gid,now,now,now),
            )
            job_id = int(con.execute("SELECT MAX(id) FROM queue").fetchone()[0])
            con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active' WHERE campaign_id='album_canary_01'")
        with self.assertRaisesRegex(RuntimeError, "Explicit confirmation"):
            reconcile_visual_canary_sent(self.db, job_id=job_id, confirmation="NO")
        out = reconcile_visual_canary_sent(
            self.db, job_id=job_id, confirmation="ALBUM_VISUALLY_CONFIRMED_SENT"
        )
        self.assertTrue(out["ok"])
        self.assertFalse(out["telegram_send_performed"])
        self.assertEqual(out["previous_status"], "retry")
        with self.db.connect() as con:
            q = con.execute("SELECT status,error_kind,resolved_at FROM queue WHERE id=?", (job_id,)).fetchone()
            c = con.execute("SELECT lifecycle_state,enabled FROM campaigns WHERE campaign_id='album_canary_01'").fetchone()
            usage = con.execute("SELECT use_count FROM content_usage WHERE campaign_id='album_canary_01' AND group_id=? AND content_id='main_ad_01_fixed'", (gid,)).fetchone()
        self.assertEqual(q[0], "sent")
        self.assertEqual(q[1], "visual_reconciled_sent")
        self.assertIsNotNone(q[2])
        self.assertEqual(tuple(c), ("paused", 0))
        self.assertEqual(usage[0], 1)

    def test_visual_reconcile_rejects_stale_job_id(self):
        self._content("main_ad_01_fixed", "Caption 1", 10)
        result = bootstrap_production(self.db, "Australia/Adelaide", ProductionBootstrapSpec())
        gid = result["canary"]["destination_id"]
        now = utcnow()
        with self.db.connect() as con:
            for key in ("older", "latest"):
                con.execute(
                    """INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,max_attempts,created_at,updated_at)
                       VALUES(?,?, 'album_canary_01',?,'main_ad_01_fixed',?,'retry',1,4,?,?)""",
                    (key,key,gid,now,now,now),
                )
            ids = [int(r[0]) for r in con.execute("SELECT id FROM queue ORDER BY id").fetchall()]
        with self.assertRaisesRegex(RuntimeError, "bound to latest job"):
            reconcile_visual_canary_sent(
                self.db, job_id=ids[0], confirmation="ALBUM_VISUALLY_CONFIRMED_SENT"
            )

    def test_album_delivery_plan_and_explicit_apply_convert_only_selected_text_destinations(self):
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at)
                   VALUES(-1003,'Production Text',1,0,'primary','text',1,0,?)""",
                (now,),
            )
        self._content("main_ad_01_fixed", "Caption 1", 10)
        bootstrap_production(self.db, "Australia/Adelaide", ProductionBootstrapSpec(configure_canary=False))
        before = album_delivery_plan(self.db)
        self.assertEqual(before["selected"], 2)
        self.assertEqual(before["photo_destinations"], 1)
        self.assertEqual(before["text_destinations"], 1)
        with self.assertRaisesRegex(RuntimeError, "APPLY_PHOTO_MODE"):
            apply_album_delivery_modes(self.db, confirmation="NO")
        after = apply_album_delivery_modes(self.db, confirmation="APPLY_PHOTO_MODE")
        self.assertEqual(after["text_destinations"], 0)
        self.assertEqual(after["photo_destinations"], 2)
        self.assertEqual(after["changed_count"], 1)
        with self.db.connect() as con:
            mode = con.execute("SELECT mode FROM destinations WHERE group_id=-1003").fetchone()[0]
            tags = {r[0] for r in con.execute("SELECT tag FROM destination_tags WHERE group_id=-1003").fetchall()}
            canary_mode = con.execute("SELECT mode FROM destinations WHERE group_id=-1002").fetchone()[0]
        self.assertEqual(mode, "photo")
        self.assertIn("auto_photo", tags)
        self.assertNotIn("auto_text", tags)
        self.assertEqual(canary_mode, "text")

    def test_album_delivery_apply_blocked_when_campaign_active(self):
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at)
                   VALUES(-1003,'Production Text',1,0,'primary','text',1,0,?)""",
                (now,),
            )
        self._content("main_ad_01_fixed", "Caption 1", 10)
        bootstrap_production(self.db, "Australia/Adelaide", ProductionBootstrapSpec(configure_canary=False))
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active' WHERE campaign_id='main_production_01'")
        with self.assertRaisesRegex(RuntimeError, "inactive"):
            apply_album_delivery_modes(self.db, confirmation="APPLY_PHOTO_MODE")

    def test_bootstrap_blocks_album_over_ten_items(self):
        self._content("main_ad_01", "Caption", 11)
        with self.assertRaisesRegex(RuntimeError, "10-item Telegram album limit"):
            bootstrap_production(
                self.db,
                "Australia/Adelaide",
                ProductionBootstrapSpec(configure_canary=False),
            )


class FakeMessage:
    def __init__(self, ident):
        self.id = ident


class FakeClient:
    def __init__(self):
        self.calls = []

    async def get_entity(self, group_id):
        return group_id

    async def send_file(self, entity, files, caption=None, **kwargs):
        self.calls.append((entity, files, caption, kwargs))
        return [FakeMessage(i + 1) for i in range(len(files))]


class FakeCache:
    async def get(self, files):
        return None


class V305AlbumSendTests(unittest.IsolatedAsyncioTestCase):
    async def test_ten_media_files_are_sent_as_one_send_file_album_call(self):
        pool = TelegramPool(1, "hash", {"primary": "unused"})
        fake = FakeClient()
        pool.clients["primary"] = fake
        pool.media_caches["primary"] = FakeCache()
        files = [f"photo_{i}.jpg" for i in range(10)]
        ids = await pool.send("primary", -1001, "caption", files, "photo")
        self.assertEqual(ids, list(range(1, 11)))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(len(fake.calls[0][1]), 10)
        self.assertEqual(fake.calls[0][2], "caption")


if __name__ == "__main__":
    unittest.main()
