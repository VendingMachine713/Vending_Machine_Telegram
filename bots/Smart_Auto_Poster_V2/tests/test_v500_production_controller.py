import asyncio
import tempfile
import unittest
from pathlib import Path

import sys
import types
telethon = types.ModuleType("telethon")
class DummyClient: pass
telethon.TelegramClient = DummyClient
errs = types.SimpleNamespace()
for name in ["FloodWaitError","SlowModeWaitError","ChatWriteForbiddenError","ChatSendMediaForbiddenError","ChatSendPhotosForbiddenError","ChatSendPlainForbiddenError","UserBannedInChannelError"]:
    setattr(errs,name,type(name,(Exception,),{}))
telethon.errors = errs
sys.modules.setdefault("telethon", telethon)

from smart_autoposter.core import create_campaign, create_content, enqueue_campaign
from smart_autoposter.db import Database, SCHEMA_VERSION, utcnow
from smart_autoposter.destination_sync import sync_destinations
from smart_autoposter.queue_hygiene import queue_hygiene_plan, apply_queue_hygiene, install_active_group_guard
from smart_autoposter.v5_controller import production_gate
from smart_autoposter.worker import Worker


class V500ProductionControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.db=Database(self.root/'db.sqlite3'); self.db.init(); self.now=utcnow()
        create_content(self.db,'text','hello',[])
        create_campaign(self.db,'main_production_01','Main','text',tags='main')
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET lifecycle_state='paused',enabled=0,last_preview_at=? WHERE campaign_id='main_production_01'",(self.now,))
            con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'G',1,1,'both','text',1,0,?)",(self.now,))
            con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(-1001,'main')")
    def tearDown(self): self.tmp.cleanup()

    def _activate(self):
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET lifecycle_state='active',enabled=1 WHERE campaign_id='main_production_01'")

    def test_v5_schema_tables(self):
        self.assertEqual(SCHEMA_VERSION,20)
        with self.db.connect() as con:
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'destination_account_capabilities','destination_timing_profiles','production_runs'}.issubset(tables))

    def test_hygiene_suppresses_only_redundant_unsent_rows(self):
        self._activate(); enqueue_campaign(self.db,'main_production_01',run_key='old')
        with self.db.connect() as con:
            first=con.execute("SELECT * FROM queue").fetchone()
            con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('legacy','new','main_production_01',-1001,'text',?,'pending',?,?)",(self.now,self.now,self.now))
        plan=queue_hygiene_plan(self.db)
        self.assertEqual(plan['safe_suppressions'],1)
        result=apply_queue_hygiene(self.db)
        self.assertEqual(result['applied'],1)
        with self.db.connect() as con:
            rows=[tuple(r) for r in con.execute("SELECT id,status,error_kind FROM queue ORDER BY id")]
        self.assertEqual(rows[0][1],'pending')
        self.assertEqual(rows[1][1:],('cancelled','duplicate_suppressed'))

    def test_uncertain_is_preserved_and_unsent_overlap_is_suppressed(self):
        self._activate(); enqueue_campaign(self.db,'main_production_01',run_key='old')
        with self.db.connect() as con:
            first=con.execute("SELECT id FROM queue").fetchone()[0]
            con.execute("UPDATE queue SET status='uncertain',error_kind='send_timeout_uncertain' WHERE id=?",(first,))
            con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('legacy','new','main_production_01',-1001,'text',?,'deferred',?,?)",(self.now,self.now,self.now))
        result=apply_queue_hygiene(self.db)
        with self.db.connect() as con:
            rows=[tuple(r) for r in con.execute("SELECT status,error_kind FROM queue ORDER BY id")]
        self.assertEqual(rows[0],('uncertain','send_timeout_uncertain'))
        self.assertEqual(rows[1],('cancelled','duplicate_suppressed'))
        self.assertEqual(result['uncertain_mutated'],False)

    def test_uncertain_attempt_evidence_is_never_suppressed(self):
        self._activate(); enqueue_campaign(self.db,'main_production_01',run_key='old')
        with self.db.connect() as con:
            first=con.execute("SELECT id FROM queue").fetchone()[0]
            con.execute("UPDATE queue SET status='uncertain' WHERE id=?",(first,))
            con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,created_at,updated_at) VALUES('legacy','new','main_production_01',-1001,'text',?,'retry',1,?,?)",(self.now,self.now,self.now))
            qid=con.execute("SELECT MAX(id) FROM queue").fetchone()[0]
            con.execute("INSERT INTO delivery_attempts(created_at,queue_id,run_key,campaign_id,group_id,attempt_number,outcome,error_kind) VALUES(?,?,?,?,?,?,?,?)",(self.now,qid,'new','main_production_01',-1001,1,'uncertain','uncertain_telegram_ack'))
        plan=queue_hygiene_plan(self.db)
        self.assertEqual(plan['safe_suppressions'],0)
        self.assertGreaterEqual(plan['review_count'],1)

    def test_per_account_capability_routing(self):
        with self.db.connect() as con:
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,health_score,updated_at) VALUES('primary','p',1,1,100,?)",(self.now,))
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,health_score,updated_at) VALUES('secondary','s',1,1,90,?)",(self.now,))
            con.execute("INSERT INTO destination_account_capabilities(group_id,account_key,text_allowed,photo_allowed,source,observed_at) VALUES(-1001,'primary',0,1,'test',?)",(self.now,))
            con.execute("INSERT INTO destination_account_capabilities(group_id,account_key,text_allowed,photo_allowed,source,observed_at) VALUES(-1001,'secondary',1,1,'test',?)",(self.now,))
        job={'group_id':-1001,'mode':'text','preferred_account':'both','primary_access':1,'secondary_access':1,'account_key':None}
        auth={'primary':{'authorized':True},'secondary':{'authorized':True}}
        self.assertEqual(Worker(self.db,object(),min_send_gap_seconds=0).choose_account(job,auth)[0],'secondary')

    def test_format_restriction_switches_account_before_switching_mode(self):
        self._activate(); enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as con:
            job=dict(con.execute("SELECT q.*,d.mode,d.primary_access,d.secondary_access FROM queue q JOIN destinations d ON d.group_id=q.group_id").fetchone())
            con.execute("INSERT INTO destination_account_capabilities(group_id,account_key,text_allowed,photo_allowed,source,observed_at) VALUES(-1001,'secondary',1,1,'test',?)",(self.now,))
        w=Worker(self.db,object(),min_send_gap_seconds=0)
        self.assertTrue(w.defer_format_fallback(job,'text_forbidden','primary'))
        with self.db.connect() as con:
            row=con.execute("SELECT status,account_key,content_id FROM queue WHERE id=?",(job['id'],)).fetchone()
            dest=con.execute("SELECT mode FROM destinations WHERE group_id=-1001").fetchone()
        self.assertEqual(row['status'],'deferred')
        self.assertIsNone(row['account_key'])
        self.assertEqual(dest['mode'],'text')

    def test_sync_persists_capability_per_account(self):
        class Pool:
            async def dialogs(_,key):
                return [{'group_id':-1001,'group_name':'G','chat_type':'supergroup','username':None,'forum':False,
                         'text_allowed': key=='secondary','photo_allowed':True,'capability_source':'scan'}]
        asyncio.run(sync_destinations(self.db,Pool(),{'primary':{'authorized':True},'secondary':{'authorized':True}}))
        with self.db.connect() as con:
            rows=[tuple(r) for r in con.execute("SELECT account_key,text_allowed,photo_allowed FROM destination_account_capabilities WHERE group_id=-1001 ORDER BY account_key")]
        self.assertEqual(rows,[('primary',0,1),('secondary',1,1)])

    def test_timing_profile_learns_slow_mode(self):
        self._activate(); enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as con: job=dict(con.execute("SELECT * FROM queue").fetchone())
        Worker(self.db,object(),min_send_gap_seconds=0).finish_error(job,'slow',retry_at=self.now,kind='slow_mode',account='primary')
        with self.db.connect() as con: row=con.execute("SELECT slow_mode_events FROM destination_timing_profiles WHERE group_id=-1001").fetchone()
        self.assertEqual(row[0],1)

    def test_gate_blocks_uncertain_and_overlap(self):
        self._activate(); enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as con:
            con.execute("UPDATE queue SET status='uncertain' WHERE id=(SELECT MIN(id) FROM queue)")
        gate=production_gate(self.db)
        self.assertFalse(gate['ready'])
        self.assertTrue(any('UNCERTAIN' in x for x in gate['blockers']))

    def test_database_unique_guard_blocks_second_unresolved_group_row(self):
        self._activate(); enqueue_campaign(self.db,'main_production_01',run_key='r')
        self.assertTrue(install_active_group_guard(self.db)['installed'])
        with self.db.connect() as con:
            with self.assertRaises(Exception):
                con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('dup','r2','main_production_01',-1001,'text',?,'pending',?,?)",(self.now,self.now,self.now))


    def test_multiple_uncertain_rows_block_guard_without_exception(self):
        self._activate(); enqueue_campaign(self.db,'main_production_01',run_key='u1')
        with self.db.connect() as con:
            first=con.execute("SELECT id FROM queue").fetchone()[0]
            con.execute("UPDATE queue SET status='uncertain',error_kind='send_timeout_uncertain' WHERE id=?",(first,))
            con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,error_kind,created_at,updated_at) VALUES('u2','u2','main_production_01',-1001,'text',?,'uncertain','interrupted_send',?,?)",(self.now,self.now,self.now))
        plan=queue_hygiene_plan(self.db)
        self.assertGreaterEqual(plan['review_count'],1)
        result=install_active_group_guard(self.db)
        self.assertFalse(result['installed'])
        self.assertTrue(result['degraded_safe_mode'])
        self.assertTrue(result['application_guards_active'])
        self.assertEqual(len(result['conflicts']),1)
        with self.db.connect() as con:
            rows=[tuple(r) for r in con.execute("SELECT status,error_kind FROM queue ORDER BY id")]
        self.assertEqual(rows,[('uncertain','send_timeout_uncertain'),('uncertain','interrupted_send')])

    def test_guard_conflict_inventory_reports_active_rows(self):
        from smart_autoposter.queue_hygiene import active_group_conflicts
        self._activate(); enqueue_campaign(self.db,'main_production_01',run_key='c1')
        with self.db.connect() as con:
            con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('c2','c2','main_production_01',-1001,'text',?,'pending',?,?)",(self.now,self.now,self.now))
        conflicts=active_group_conflicts(self.db)
        self.assertEqual(len(conflicts),1)
        self.assertEqual(conflicts[0]['active_count'],2)

    def test_production_run_ledger_written(self):
        self._activate(); result=enqueue_campaign(self.db,'main_production_01',run_key='ledger')
        with self.db.connect() as con: row=con.execute("SELECT target_count,inserted_count FROM production_runs WHERE run_key='ledger'").fetchone()
        self.assertEqual(tuple(row),(1,result['inserted']))

    def test_v5_cli_and_control_panel_surfaces(self):
        from smart_autoposter import __version__
        from smart_autoposter.cli import build_parser
        self.assertEqual(__version__,'6.0.1')
        parser=build_parser()
        self.assertEqual(parser.parse_args(['queue-hygiene']).func.__name__,'cmd_queue_hygiene')
        self.assertEqual(parser.parse_args(['v5-readiness']).func.__name__,'cmd_v5_readiness')
        panel=(Path(__file__).parents[1]/'CONTROL_PANEL.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('92. V5 queue hygiene plan',panel)
        self.assertIn('93. V5 production gate',panel)
        self.assertIn('94. V5 apply SAFE queue hygiene',panel)

    def test_admin_exposes_gate_and_hygiene(self):
        text=(Path(__file__).parents[1]/'smart_autoposter'/'admin_bot.py').read_text(encoding='utf-8')
        self.assertIn('/gate',text); self.assertIn('/hygiene',text)

if __name__=='__main__': unittest.main()
