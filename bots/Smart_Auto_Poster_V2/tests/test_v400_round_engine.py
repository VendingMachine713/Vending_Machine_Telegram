import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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
]:
    setattr(errs, name, type(name, (Exception,), {}))
telethon.errors = errs
sys.modules.setdefault("telethon", telethon)

from smart_autoposter.core import add_campaign_content, create_campaign, create_content, enqueue_campaign
from smart_autoposter.db import Database, SCHEMA_VERSION, utcnow
from smart_autoposter.destination_sync import sync_destinations
from smart_autoposter.mission_control import mission_snapshot
from smart_autoposter.progress import post_pipeline_snapshot, progress_snapshot
from smart_autoposter.telegram_io import infer_destination_capabilities
from smart_autoposter.worker import Worker


class V400RoundEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "db.sqlite3")
        self.db.init()
        self.now = utcnow()

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_campaign(self, *, campaign="camp", tags="main"):
        photo = self.root / "one.jpg"; photo.write_bytes(b"x")
        create_content(self.db, "photo", "photo caption", [str(photo)])
        create_content(self.db, "text", "text caption", [])
        create_campaign(self.db, campaign, "Campaign", "photo", tags=tags)
        add_campaign_content(self.db, campaign, "text", position=1)
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active',last_preview_at=? WHERE campaign_id=?", (self.now, campaign))

    def _dest(self, gid, mode="text", tag="main"):
        with self.db.connect() as con:
            con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (gid, f"G{abs(gid)}", 1, 0, "primary", mode, 1, 0, self.now))
            con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(?,?)", (gid, tag))

    def test_v4_schema_and_phase_history_exist(self):
        self.assertGreaterEqual(SCHEMA_VERSION, 20)
        with self.db.connect() as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            cols = {r[1] for r in con.execute("PRAGMA table_info(queue)")}
        self.assertIn("queue_phase_history", tables)
        self.assertTrue({"pass_no","phase","phase_percent","deferral_count","progress_current","progress_total"}.issubset(cols))

    def test_capability_inference_for_readonly_broadcast(self):
        entity = SimpleNamespace(broadcast=True, megagroup=False, creator=False, admin_rights=None)
        caps = infer_destination_capabilities(entity)
        self.assertEqual((caps["text_allowed"], caps["photo_allowed"]), (False, False))

    def test_capability_inference_for_text_only_group(self):
        rights = SimpleNamespace(send_messages=False, send_media=True, send_photos=True)
        entity = SimpleNamespace(broadcast=False, megagroup=True, creator=False, admin_rights=None, default_banned_rights=rights)
        caps = infer_destination_capabilities(entity)
        self.assertEqual((caps["text_allowed"], caps["photo_allowed"]), (True, False))

    def test_sync_learns_text_only_and_switches_mode(self):
        self._dest(-1001, mode="photo")
        class Pool:
            async def dialogs(_, account):
                if account == "primary":
                    return [{"group_id":-1001,"group_name":"G","chat_type":"supergroup","username":None,"forum":False,
                             "text_allowed":True,"photo_allowed":False,"capability_source":"telegram_default_rights"}]
                return []
        auth={"primary":{"authorized":True},"secondary":{"authorized":True}}
        result=asyncio.run(sync_destinations(self.db, Pool(), auth))
        with self.db.connect() as con:
            row=con.execute("SELECT mode,text_allowed,photo_allowed,enabled FROM destinations WHERE group_id=-1001").fetchone()
        self.assertEqual(tuple(row), ("text",1,0,1))
        self.assertGreaterEqual(result["mode_changed"],1)

    def test_sync_unions_capability_across_accounts(self):
        self._dest(-1001, mode="photo")
        class Pool:
            async def dialogs(_, account):
                if account == "primary":
                    return [{"group_id":-1001,"group_name":"G","chat_type":"channel","username":None,"forum":False,
                             "text_allowed":False,"photo_allowed":False,"capability_source":"telegram_broadcast_readonly"}]
                return [{"group_id":-1001,"group_name":"G","chat_type":"channel","username":None,"forum":False,
                         "text_allowed":True,"photo_allowed":True,"capability_source":"telegram_admin_rights"}]
        auth={"primary":{"authorized":True},"secondary":{"authorized":True}}
        asyncio.run(sync_destinations(self.db, Pool(), auth))
        with self.db.connect() as con:
            row=con.execute("SELECT text_allowed,photo_allowed,enabled FROM destinations WHERE group_id=-1001").fetchone()
        self.assertEqual(tuple(row),(1,1,1))

    def test_enqueue_routes_mixed_formats_and_never_stacks_group(self):
        self._seed_campaign(); self._dest(-1001,"text"); self._dest(-1002,"photo")
        first=enqueue_campaign(self.db,"camp",run_key="round:1")
        self.assertEqual(first["inserted"],2)
        with self.db.connect() as con:
            rows={r["group_id"]:dict(r) for r in con.execute("SELECT q.group_id,q.content_id,d.mode,c.caption,c.media_json FROM queue q JOIN destinations d ON d.group_id=q.group_id JOIN content c ON c.content_id=q.content_id")}
        self.assertEqual(rows[-1001]["mode"],"text")
        self.assertTrue(rows[-1001]["caption"].strip())
        self.assertEqual(rows[-1002]["mode"],"photo")
        self.assertNotEqual(rows[-1002]["media_json"],"[]")
        second=enqueue_campaign(self.db,"camp",run_key="round:2")
        self.assertEqual(second["inserted"],0)
        self.assertEqual(second["overlap_locked"],2)

    def test_pass_two_waits_until_pass_one_drains(self):
        self._seed_campaign(); self._dest(-1001,"text"); self._dest(-1002,"text")
        enqueue_campaign(self.db,"camp",run_key="r")
        with self.db.connect() as con:
            rows=con.execute("SELECT id,group_id FROM queue ORDER BY id").fetchall()
            con.execute("UPDATE queue SET status='deferred',pass_no=2,due_at=?,phase='deferred' WHERE id=?", (self.now, rows[0]["id"]))
        worker=Worker(self.db, object(), min_send_gap_seconds=0)
        claimed=worker.claim()
        self.assertEqual(claimed["group_id"], rows[1]["group_id"])
        self.assertEqual(claimed["pass_no"],1)

    def test_slowmode_defer_reuses_same_row_without_attempt_budget(self):
        self._seed_campaign(); self._dest(-1001,"text")
        enqueue_campaign(self.db,"camp",run_key="r")
        with self.db.connect() as con: job=dict(con.execute("SELECT * FROM queue").fetchone())
        worker=Worker(self.db, object(), min_send_gap_seconds=0)
        worker.finish_error(job,"slow_mode: wait",permanent=False,retry_at=self.now,account="primary",kind="slow_mode")
        with self.db.connect() as con:
            row=con.execute("SELECT id,status,attempts,pass_no,deferral_count,error_kind FROM queue").fetchone()
        self.assertEqual(tuple(row),(job["id"],"deferred",0,2,1,"slow_mode"))

    def test_uncertain_row_blocks_other_same_group_claim(self):
        self._seed_campaign(); self._dest(-1001,"text")
        enqueue_campaign(self.db,"camp",run_key="r")
        with self.db.connect() as con:
            first=con.execute("SELECT * FROM queue").fetchone()
            con.execute("UPDATE queue SET status='uncertain' WHERE id=?",(first["id"],))
            con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('legacy2','legacy','camp',-1001,'text',?,'pending',?,?)",(self.now,self.now,self.now))
        self.assertIsNone(Worker(self.db, object(), min_send_gap_seconds=0).claim())

    def test_definitive_send_suppresses_legacy_pre_send_duplicate(self):
        self._seed_campaign(); self._dest(-1001,"text")
        enqueue_campaign(self.db,"camp",run_key="r")
        with self.db.connect() as con:
            con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('legacy2','legacy','camp',-1001,'text',?,'pending',?,?)",(self.now,self.now,self.now))
        class Pool:
            async def send(self,*args,**kwargs): return [123]
        auth={"primary":{"authorized":True},"secondary":{"authorized":False}}
        worker=Worker(self.db,Pool(),min_send_gap_seconds=0)
        asyncio.run(worker.run_once(auth))
        with self.db.connect() as con:
            rows=[tuple(r) for r in con.execute("SELECT status,error_kind FROM queue ORDER BY id")]
        self.assertEqual(rows[0][0],"sent")
        self.assertEqual(rows[1],("cancelled","duplicate_suppressed"))

    def test_format_fallback_without_compatible_content_fails_terminally(self):
        # Campaign has text only; if Telegram rejects text and requires photo, do not loop retries forever.
        create_content(self.db, "textonly", "caption", [])
        create_campaign(self.db, "camp", "Campaign", "textonly", tags="main")
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active',last_preview_at=? WHERE campaign_id='camp'", (self.now,))
        self._dest(-1001,"text")
        enqueue_campaign(self.db,"camp",run_key="r")
        with self.db.connect() as con: job=dict(con.execute("SELECT q.*,d.mode FROM queue q JOIN destinations d ON d.group_id=q.group_id").fetchone())
        worker=Worker(self.db,object(),min_send_gap_seconds=0)
        self.assertTrue(worker.defer_format_fallback(job,"text_forbidden","primary"))
        with self.db.connect() as con:
            row=con.execute("SELECT status,error_kind,attempts FROM queue").fetchone()
        self.assertEqual(tuple(row),("failed","no_compatible_fallback",0))

    def test_upload_progress_and_pipeline_history_are_durable(self):
        self._seed_campaign(); self._dest(-1001,"photo")
        enqueue_campaign(self.db,"camp",run_key="r")
        class Pool:
            async def send(self, account, group_id, caption, media, mode, topic_id, progress_callback=None, stage_callback=None):
                if stage_callback: stage_callback("resolving_destination",58,"resolving")
                if progress_callback:
                    progress_callback(25,100); progress_callback(50,100); progress_callback(100,100)
                if stage_callback: stage_callback("awaiting_ack",90,"ack")
                return [1,2]
        worker=Worker(self.db,Pool(),min_send_gap_seconds=0)
        asyncio.run(worker.run_once({"primary":{"authorized":True},"secondary":{"authorized":False}}))
        with self.db.connect() as con: jid=con.execute("SELECT id FROM queue").fetchone()[0]
        pipe=post_pipeline_snapshot(self.db,jid)
        phases=[p["phase"] for p in pipe["phases"]]
        self.assertIn("uploading_media",phases)
        self.assertIn("sent",phases)
        self.assertEqual(pipe["job"]["status"],"sent")

    def test_post_pipeline_renders_step_checklist_and_ascii_details(self):
        self._seed_campaign(); self._dest(-1001,"text")
        enqueue_campaign(self.db,"camp",run_key="r")
        with self.db.connect() as con:
            jid=con.execute("SELECT id FROM queue").fetchone()[0]
            con.execute("UPDATE queue SET status='processing',phase='selecting_account',phase_percent=32,phase_detail='routing account',phase_updated_at=?,updated_at=? WHERE id=?", (self.now,self.now,jid))
        from smart_autoposter.progress import render_post_pipeline, render_progress_text
        text=render_post_pipeline(post_pipeline_snapshot(self.db,jid),emoji=False)
        self.assertIn("CURRENT PASS CHECKLIST",text)
        self.assertIn("[>] Telegram account selected",text)
        overview=render_progress_text(progress_snapshot(self.db,campaign_id="camp"),emoji=False)
        self.assertNotIn("â€¢",overview)

    def test_v4_release_surfaces_are_exposed(self):
        from smart_autoposter import __version__
        from smart_autoposter.cli import build_parser
        self.assertEqual(__version__, "6.0.1")
        parser=build_parser()
        self.assertEqual(parser.parse_args(["mission-control"]).func.__name__, "cmd_mission_control")
        self.assertEqual(parser.parse_args(["job-timeline","36"]).func.__name__, "cmd_job_timeline")
        root=Path(__file__).parents[1]
        panel=(root/"CONTROL_PANEL.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("90. V4 Mission Control",panel)
        self.assertIn("91. Inspect one post pipeline",panel)
        self.assertIn("mission-control",panel)
        self.assertIn("job-timeline",panel)

    def test_mission_control_detects_global_legacy_overlap(self):
        self._seed_campaign(); self._dest(-1001,"text")
        enqueue_campaign(self.db,"camp",run_key="r")
        with self.db.connect() as con:
            con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('legacy2','legacy','camp',-1001,'text',?,'pending',?,?)",(self.now,self.now,self.now))
        snap=mission_snapshot(self.db,campaign_id="camp")
        self.assertFalse(snap["anti_spam_ok"])
        self.assertEqual(snap["duplicate_unresolved_group_sets"],1)


if __name__ == "__main__":
    unittest.main()
