import tempfile, unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
import sys, types
telethon=types.ModuleType('telethon'); telethon.TelegramClient=type('DummyClient',(),{})
errs=types.SimpleNamespace()
for n in ['FloodWaitError','SlowModeWaitError','ChatWriteForbiddenError','ChatSendMediaForbiddenError','ChatSendPhotosForbiddenError','ChatSendPlainForbiddenError','UserBannedInChannelError']:
    setattr(errs,n,type(n,(Exception,),{}))
telethon.errors=errs; sys.modules.setdefault('telethon',telethon)

from smart_autoposter.db import Database,SCHEMA_VERSION,utcnow
from smart_autoposter.core import create_content,create_campaign,enqueue_campaign
from smart_autoposter.v6_controller import refresh_destination_intelligence,refresh_delivery_confidence,predictive_plan,recovery_snapshot,production_health,v6_readiness,render_v6_control
from smart_autoposter.worker import Worker

class V600ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); self.db=Database(self.root/'d.db'); self.db.init(); self.now=utcnow()
        create_content(self.db,'txt','hello',[]); create_campaign(self.db,'main_production_01','Main','txt',tags='main')
        with self.db.connect() as c:
            c.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active',last_preview_at=? WHERE campaign_id='main_production_01'",(self.now,))
            for key,health in [('primary',90),('secondary',80)]:
                c.execute("INSERT OR REPLACE INTO accounts(account_key,session_name,enabled,authorized,health_score,updated_at) VALUES(?,?,?,?,?,?)",(key,key,1,1,health,self.now))
            c.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-100,'G',1,1,'both','text',1,0,?)",(self.now,))
            c.execute("INSERT INTO destination_tags(group_id,tag) VALUES(-100,'main')")
    def tearDown(self): self.t.cleanup()

    def test_schema_v20_has_v6_tables(self):
        self.assertEqual(SCHEMA_VERSION,20)
        with self.db.connect() as c:
            names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'destination_intelligence','delivery_confidence','recovery_incidents','production_objectives'} <= names)

    def test_destination_intelligence_prefers_healthiest_compatible_account(self):
        rows=refresh_destination_intelligence(self.db); x=next(r for r in rows if r['group_id']==-100)
        self.assertEqual(x['preferred_account'],'primary'); self.assertGreaterEqual(x['reliability'],0)

    def test_account_specific_format_restriction_changes_v6_preference(self):
        with self.db.connect() as c:
            c.execute("UPDATE destinations SET mode='photo' WHERE group_id=-100")
            c.execute("INSERT INTO destination_account_capabilities(group_id,account_key,text_allowed,photo_allowed,source,observed_at) VALUES(-100,'primary',1,0,'test',?)",(self.now,))
            c.execute("INSERT INTO destination_account_capabilities(group_id,account_key,text_allowed,photo_allowed,source,observed_at) VALUES(-100,'secondary',1,1,'test',?)",(self.now,))
        x=next(r for r in refresh_destination_intelligence(self.db) if r['group_id']==-100)
        self.assertEqual(x['preferred_account'],'secondary')

    def test_delivery_confidence_sent_ids_is_100(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as c:
            q=c.execute("SELECT id FROM queue LIMIT 1").fetchone()['id']; c.execute("UPDATE queue SET status='sent',telegram_message_ids='[1,2]' WHERE id=?",(q,))
        x=next(r for r in refresh_delivery_confidence(self.db) if r['queue_id']==q)
        self.assertEqual(x['confidence'],100); self.assertEqual(x['verdict'],'confirmed_sent')

    def test_delivery_confidence_uncertain_never_becomes_confirmed(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as c:
            q=c.execute("SELECT id FROM queue LIMIT 1").fetchone()['id']; c.execute("UPDATE queue SET status='uncertain',error_kind='send_timeout_uncertain' WHERE id=?",(q,))
        x=next(r for r in refresh_delivery_confidence(self.db) if r['queue_id']==q)
        self.assertEqual(x['verdict'],'uncertain'); self.assertLess(x['confidence'],100)

    def test_predictive_plan_blocks_existing_obligation(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r')
        p=predictive_plan(self.db); self.assertEqual(p['counts']['review'],1); self.assertEqual(p['review'][0]['reason'],'existing_unresolved_obligation')

    def test_predictive_plan_waits_for_learned_timing(self):
        future=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(timespec='seconds')
        with self.db.connect() as c:
            c.execute("INSERT INTO destination_timing_profiles(group_id,next_safe_at,updated_at) VALUES(-100,?,?)",(future,self.now))
        p=predictive_plan(self.db); self.assertEqual(p['counts']['timing_wait'],1)

    def test_worker_predictive_hold_uses_same_row(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r')
        future=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(timespec='seconds')
        with self.db.connect() as c: c.execute("INSERT INTO destination_timing_profiles(group_id,next_safe_at,updated_at) VALUES(-100,?,?)",(future,self.now))
        w=Worker(self.db,object()); job=w.claim(); hold=w.predictive_timing_hold(job); self.assertIsNotNone(hold)
        w.defer_job(job,hold.isoformat(timespec='seconds'),'predictive',kind='predictive_timing')
        with self.db.connect() as c:
            rows=c.execute("SELECT id,status,error_kind FROM queue WHERE group_id=-100").fetchall()
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]['status'],'deferred'); self.assertEqual(rows[0]['error_kind'],'predictive_timing')

    def test_recovery_snapshot_flags_stale_service_as_auto_safe_without_inflight(self):
        old=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat(timespec='seconds')
        with self.db.connect() as c: c.execute("INSERT OR REPLACE INTO heartbeats(component,last_seen_at,status,details) VALUES('service',?,'ok',NULL)",(old,))
        r=recovery_snapshot(self.db); self.assertTrue(any(a['component']=='service' and a['automatic_safe'] for a in r['recommended_actions']))

    def test_recovery_snapshot_does_not_auto_restart_during_sending(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r')
        old=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat(timespec='seconds')
        with self.db.connect() as c:
            c.execute("UPDATE queue SET status='sending' WHERE group_id=-100")
            c.execute("INSERT OR REPLACE INTO heartbeats(component,last_seen_at,status,details) VALUES('service',?,'ok',NULL)",(old,))
        r=recovery_snapshot(self.db); self.assertTrue(any(a['component']=='service' and not a['automatic_safe'] for a in r['recommended_actions']))

    def test_v6_gate_fail_closed_with_uncertain(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as c: c.execute("UPDATE queue SET status='uncertain' WHERE group_id=-100")
        g=v6_readiness(self.db); self.assertFalse(g['ready']); self.assertEqual(g['uncertain'],1)

    def test_v6_control_render_is_console_safe_ascii(self):
        snap=v6_readiness(self.db); txt=render_v6_control(snap); txt.encode('ascii'); self.assertIn('V6 CONTROL PLANE',txt)

    def test_production_health_penalizes_uncertain(self):
        base=production_health(self.db)['health_score']; enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as c: c.execute("UPDATE queue SET status='uncertain' WHERE group_id=-100")
        self.assertLess(production_health(self.db)['health_score'],base)

if __name__=='__main__': unittest.main()
