import tempfile, unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
import sys,types
telethon=types.ModuleType('telethon'); telethon.TelegramClient=type('DummyClient',(),{})
errs=types.SimpleNamespace()
for n in ['FloodWaitError','SlowModeWaitError','ChatWriteForbiddenError','ChatSendMediaForbiddenError','ChatSendPhotosForbiddenError','ChatSendPlainForbiddenError','UserBannedInChannelError']:
    setattr(errs,n,type(n,(Exception,),{}))
telethon.errors=errs; sys.modules.setdefault('telethon',telethon)
from smart_autoposter.db import Database,utcnow
from smart_autoposter.core import create_content,create_campaign,enqueue_campaign
from smart_autoposter.v6_controller import predictive_plan,v6_readiness,production_health,refresh_destination_intelligence

class V600Soak(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.db=Database(Path(self.t.name)/'d.db'); self.db.init(); now=utcnow()
        create_content(self.db,'txt','hello',[]); create_campaign(self.db,'main_production_01','Main','txt',tags='main')
        with self.db.connect() as c:
            c.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active',last_preview_at=? WHERE campaign_id='main_production_01'",(now,))
            for key,h in [('primary',95),('secondary',90)]: c.execute("INSERT OR REPLACE INTO accounts(account_key,session_name,enabled,authorized,health_score,updated_at) VALUES(?,?,?,?,?,?)",(key,key,1,1,h,now))
            for i in range(32):
                gid=-200000-i; c.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(gid,f'G{i}',1,1,'both','text',1,0,now)); c.execute("INSERT INTO destination_tags(group_id,tag) VALUES(?,'main')",(gid,))
    def tearDown(self): self.t.cleanup()
    def test_32_destination_predictive_plan_splits_ready_and_wait(self):
        future=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(timespec='seconds')
        with self.db.connect() as c:
            for i in range(8): c.execute("INSERT INTO destination_timing_profiles(group_id,next_safe_at,updated_at) VALUES(?,?,?)",(-200000-i,future,utcnow()))
        p=predictive_plan(self.db); self.assertEqual(p['counts']['ready_now'],24); self.assertEqual(p['counts']['timing_wait'],8); self.assertEqual(p['counts']['review'],0)
    def test_next_cycle_plan_blocks_exactly_unresolved_groups(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r1')
        with self.db.connect() as c:
            rows=c.execute("SELECT id FROM queue ORDER BY id").fetchall()
            for r in rows[:20]: c.execute("UPDATE queue SET status='sent',resolved_at=? WHERE id=?",(utcnow(),r['id']))
            for r in rows[20:28]: c.execute("UPDATE queue SET status='deferred' WHERE id=?",(r['id'],))
            for r in rows[28:]: c.execute("UPDATE queue SET status='uncertain' WHERE id=?",(r['id'],))
        p=predictive_plan(self.db); self.assertEqual(p['counts']['ready_now'],20); self.assertEqual(p['counts']['review'],12)
    def test_health_score_falls_under_uncertain_storm(self):
        clean=production_health(self.db)['health_score']; enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as c: c.execute("UPDATE queue SET status='uncertain'")
        self.assertLess(production_health(self.db)['health_score'],clean)
    def test_objective_can_require_database_guard(self):
        with self.db.connect() as c: c.execute("INSERT OR REPLACE INTO production_objectives(campaign_id,require_database_guard,updated_at) VALUES('main_production_01',1,?)",(utcnow(),))
        g=v6_readiness(self.db); self.assertFalse(g['ready']); self.assertTrue(any('database one-unresolved-group guard' in x for x in g['blockers']))
    def test_intelligence_refresh_is_idempotent(self):
        a=refresh_destination_intelligence(self.db); b=refresh_destination_intelligence(self.db); self.assertEqual(len(a),32); self.assertEqual(len(b),32)
        with self.db.connect() as c: self.assertEqual(c.execute("SELECT COUNT(*) FROM destination_intelligence").fetchone()[0],32)
if __name__=='__main__': unittest.main()
