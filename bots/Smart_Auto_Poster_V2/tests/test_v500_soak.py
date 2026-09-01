import tempfile, unittest
from pathlib import Path

import sys, types
telethon=types.ModuleType('telethon'); telethon.TelegramClient=type('DummyClient',(),{})
errs=types.SimpleNamespace()
for n in ['FloodWaitError','SlowModeWaitError','ChatWriteForbiddenError','ChatSendMediaForbiddenError','ChatSendPhotosForbiddenError','ChatSendPlainForbiddenError','UserBannedInChannelError']:
    setattr(errs,n,type(n,(Exception,),{}))
telethon.errors=errs; sys.modules.setdefault('telethon',telethon)

from smart_autoposter.core import create_content,create_campaign,enqueue_campaign
from smart_autoposter.db import Database,utcnow
from smart_autoposter.queue_hygiene import apply_queue_hygiene
from smart_autoposter.v5_controller import production_gate,refresh_run_ledger
from smart_autoposter.worker import Worker

class V500SoakTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); self.db=Database(self.root/'d.db'); self.db.init(); self.now=utcnow()
        create_content(self.db,'txt','hello',[]); create_campaign(self.db,'main_production_01','Main','txt',tags='main')
        with self.db.connect() as c:
            c.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active',last_preview_at=? WHERE campaign_id='main_production_01'",(self.now,))
            for i in range(32):
                gid=-100000-i
                c.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(gid,f'G{i+1}',1,1,'both','text',1,0,self.now))
                c.execute("INSERT INTO destination_tags(group_id,tag) VALUES(?, 'main')",(gid,))
    def tearDown(self): self.t.cleanup()

    def test_32_destination_next_cycle_never_stacks_unresolved(self):
        a=enqueue_campaign(self.db,'main_production_01',run_key='cycle1'); self.assertEqual(a['inserted'],32)
        with self.db.connect() as c:
            rows=c.execute("SELECT id FROM queue ORDER BY id").fetchall()
            # 20 definitively completed, 8 deferred, 4 uncertain.
            for r in rows[:20]: c.execute("UPDATE queue SET status='sent',resolved_at=? WHERE id=?",(self.now,r['id']))
            for r in rows[20:28]: c.execute("UPDATE queue SET status='deferred',pass_no=2,error_kind='slow_mode' WHERE id=?",(r['id'],))
            for r in rows[28:]: c.execute("UPDATE queue SET status='uncertain',error_kind='send_timeout_uncertain' WHERE id=?",(r['id'],))
        b=enqueue_campaign(self.db,'main_production_01',run_key='cycle2')
        self.assertEqual(b['inserted'],20)
        self.assertEqual(b['overlap_locked'],12)
        with self.db.connect() as c:
            bad=c.execute("SELECT group_id,COUNT(*) FROM queue WHERE status IN ('pending','retry','deferred','processing','sending','uncertain') GROUP BY group_id HAVING COUNT(*)>1").fetchall()
        self.assertEqual(bad,[])

    def test_pass_barrier_drains_pass_one_before_pass_two(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as c:
            ids=[r['id'] for r in c.execute("SELECT id FROM queue ORDER BY id")]
            c.execute("UPDATE queue SET status='deferred',pass_no=2,due_at=? WHERE id=?",(self.now,ids[0]))
        w=Worker(self.db,object(),min_send_gap_seconds=0)
        claimed=w.claim(); self.assertIsNotNone(claimed); self.assertEqual(claimed['pass_no'],1); self.assertNotEqual(claimed['id'],ids[0])

    def test_legacy_stack_cleanup_preserves_one_obligation_per_group(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as c:
            first=dict(c.execute("SELECT * FROM queue ORDER BY id LIMIT 1").fetchone())
            for suffix,status in [('a','pending'),('b','deferred'),('c','retry')]:
                c.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(f'legacy{suffix}','legacy','main_production_01',first['group_id'],'txt',self.now,status,self.now,self.now))
        result=apply_queue_hygiene(self.db); self.assertEqual(result['applied'],3)
        with self.db.connect() as c:
            active=c.execute("SELECT COUNT(*) FROM queue WHERE group_id=? AND status IN ('pending','retry','deferred','processing','sending','uncertain')",(first['group_id'],)).fetchone()[0]
        self.assertEqual(active,1)

    def test_gate_remains_fail_closed_with_uncertain(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as c: c.execute("UPDATE queue SET status='uncertain' WHERE id=(SELECT MIN(id) FROM queue)")
        gate=production_gate(self.db); self.assertFalse(gate['ready']); self.assertGreater(gate['uncertain'],0)

    def test_run_ledger_marks_uncertain_attention(self):
        enqueue_campaign(self.db,'main_production_01',run_key='r')
        with self.db.connect() as c: c.execute("UPDATE queue SET status='uncertain' WHERE id=(SELECT MIN(id) FROM queue)")
        rows=refresh_run_ledger(self.db,campaign_id='main_production_01')
        self.assertEqual(next(x for x in rows if x['run_key']=='r')['state'],'attention')

if __name__=='__main__': unittest.main()
