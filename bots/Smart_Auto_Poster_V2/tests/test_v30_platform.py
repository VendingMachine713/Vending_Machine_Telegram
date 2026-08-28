import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
import types

# Test environment may not include Telethon. Stub the import surface used by the local Worker logic.
telethon = types.ModuleType("telethon")
class DummyClient: pass
telethon.TelegramClient = DummyClient
errs = types.SimpleNamespace()
for _name in [
    "FloodWaitError", "SlowModeWaitError", "ChatWriteForbiddenError",
    "ChatSendMediaForbiddenError", "ChatSendPhotosForbiddenError",
    "ChatSendPlainForbiddenError", "UserBannedInChannelError",
]:
    setattr(errs, _name, type(_name, (Exception,), {}))
telethon.errors = errs
sys.modules.setdefault("telethon", telethon)

from smart_autoposter.admin_bot import TelegramAdminController, dashboard_text
from smart_autoposter.analytics import analytics_snapshot
from smart_autoposter.collections import CollectionSpec, collection_preview, delete_collection, get_collection, resolve_collection, upsert_collection
from smart_autoposter.core import campaign_preview, create_campaign, create_content, enqueue_campaign, validate
from smart_autoposter.db import Database, utcnow
from smart_autoposter.operations import finalize_cycle_limited_campaigns, mark_campaign_previewed, set_campaign_state
from smart_autoposter.recommendations import apply_recommendation, dismiss_recommendation, generate_recommendations, list_recommendations
from smart_autoposter.reports import daily_report_text, weekly_report_text
from smart_autoposter.rules import apply_rules, list_rules, upsert_rule
from smart_autoposter.safety import SafetyController
from smart_autoposter.scheduler import Scheduler, configure_interval
from smart_autoposter.worker import Worker


class V30PlatformTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.old=Path.cwd(); os.chdir(self.root)
        self.db=Database(self.root/'data'/'test.sqlite3'); self.db.init(); now=utcnow()
        with self.db.connect() as con:
            dests=[
                (-1001,'Primary Text',1,0,'primary','text',1,0,0,0),
                (-1002,'Secondary Photo',0,1,'secondary','photo',1,0,0,0),
                (-1003,'Both Forum',1,1,'both','text',1,0,0,0),
                (-1004,'Protected Both',1,1,'both','text',1,0,1,0),
                (-1005,'Review Group',1,0,'primary','review',0,1,0,0),
            ]
            for gid,name,pa,sa,pref,mode,en,rev,prot,never in dests:
                con.execute('''INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,protected,never_auto_post,forum,updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(gid,name,pa,sa,pref,mode,en,rev,prot,never,int(gid==-1003),now))
            for gid,tag in [(-1001,'main'),(-1001,'south'),(-1002,'main'),(-1002,'north'),(-1003,'vip'),(-1003,'south'),(-1004,'vip'),(-1005,'new')]:
                con.execute('INSERT INTO destination_tags(group_id,tag) VALUES(?,?)',(gid,tag))
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,health_score,updated_at) VALUES('primary','p',1,1,'Primary',100,?)",(now,))
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,health_score,updated_at) VALUES('secondary','s',1,1,'Secondary',100,?)",(now,))
        create_content(self.db,'ad_a','A',[]); create_content(self.db,'ad_b','B',[])
        create_campaign(self.db,'camp','Campaign','ad_a',tags='main')

    def tearDown(self):
        os.chdir(self.old); self.tmp.cleanup()

    def activate(self, cid='camp'):
        mark_campaign_previewed(self.db,cid); set_campaign_state(self.db,cid,'active')

    def test_schema_v6_platform_tables_and_columns(self):
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],'6')
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({'destination_collections','automation_rules','recommendations'}.issubset(tables))
            cols={r[1] for r in con.execute('PRAGMA table_info(campaigns)')}
            self.assertTrue({'category','target_collections','max_cycles','completed_cycles'}.issubset(cols))

    def test_collection_normalizes_and_previews(self):
        upsert_collection(self.db,CollectionSpec('South','South Groups',' SOUTH , main '))
        c=get_collection(self.db,'south')
        self.assertEqual(c['include_tags'],'main,south')
        self.assertEqual(collection_preview(self.db,'south')['selected'],3)

    def test_collection_primary_access_filter(self):
        upsert_collection(self.db,CollectionSpec('p','Primary','',required_access='primary'))
        ids={r['group_id'] for r in resolve_collection(self.db,'p')}
        self.assertEqual(ids,{-1001,-1003})

    def test_collection_secondary_access_filter(self):
        upsert_collection(self.db,CollectionSpec('s','Secondary','',required_access='secondary'))
        ids={r['group_id'] for r in resolve_collection(self.db,'s')}
        self.assertEqual(ids,{-1002,-1003})

    def test_collection_both_access_filter(self):
        upsert_collection(self.db,CollectionSpec('b','Both','',required_access='both'))
        self.assertEqual({r['group_id'] for r in resolve_collection(self.db,'b')},{-1003})

    def test_collection_mode_filter(self):
        upsert_collection(self.db,CollectionSpec('photo','Photos','',mode='photo'))
        self.assertEqual([r['group_id'] for r in resolve_collection(self.db,'photo')],[-1002])

    def test_collection_forum_filter(self):
        upsert_collection(self.db,CollectionSpec('forums','Forums','',forum_only=True))
        self.assertEqual([r['group_id'] for r in resolve_collection(self.db,'forums')],[-1003])

    def test_collection_exclude_tag(self):
        upsert_collection(self.db,CollectionSpec('notnorth','Not North','main',exclude_tags='north'))
        self.assertEqual([r['group_id'] for r in resolve_collection(self.db,'notnorth')],[-1001])

    def test_collection_protected_excluded_by_default(self):
        upsert_collection(self.db,CollectionSpec('vip','VIP','vip'))
        self.assertEqual([r['group_id'] for r in resolve_collection(self.db,'vip')],[-1003])

    def test_collection_can_explicitly_include_protected(self):
        upsert_collection(self.db,CollectionSpec('vip','VIP','vip',include_protected=True))
        self.assertEqual({r['group_id'] for r in resolve_collection(self.db,'vip')},{-1003,-1004})

    def test_collection_delete_blocked_when_campaign_uses_it(self):
        upsert_collection(self.db,CollectionSpec('south','South','south'))
        create_campaign(self.db,'cc','C','ad_a',target_collections='south')
        with self.assertRaisesRegex(RuntimeError,'referenced'):
            delete_collection(self.db,'south')

    def test_campaign_collection_targeting(self):
        upsert_collection(self.db,CollectionSpec('south','South','south'))
        create_campaign(self.db,'cc','C','ad_a',target_collections='south')
        self.assertEqual(campaign_preview(self.db,'cc')['selected'],2)

    def test_campaign_tags_union_collection(self):
        upsert_collection(self.db,CollectionSpec('vip','VIP','vip'))
        create_campaign(self.db,'cc','C','ad_a',tags='north',target_collections='vip')
        self.assertEqual({r for r in campaign_preview(self.db,'cc')['accounts']}, {'primary_only','secondary_only','both'})
        self.assertEqual(campaign_preview(self.db,'cc')['selected'],2)

    def test_missing_collection_fails_validation(self):
        create_campaign(self.db,'cc','C','ad_a',target_collections='missing')
        self.assertTrue(any('missing/disabled collection missing' in x for x in validate(self.db)))

    def test_cycle_limit_increments_on_real_enqueue(self):
        create_campaign(self.db,'limited','Limited','ad_a',tags='main',max_cycles=2)
        self.activate('limited')
        enqueue_campaign(self.db,'limited',run_key='a')
        enqueue_campaign(self.db,'limited',run_key='b')
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT completed_cycles FROM campaigns WHERE campaign_id='limited'").fetchone()[0],2)

    def test_cycle_limit_blocks_extra_enqueue(self):
        create_campaign(self.db,'limited','Limited','ad_a',tags='main',max_cycles=1); self.activate('limited')
        enqueue_campaign(self.db,'limited',run_key='a')
        with self.assertRaisesRegex(RuntimeError,'cycle limit'):
            enqueue_campaign(self.db,'limited',run_key='b')

    def test_duplicate_run_does_not_consume_cycle(self):
        create_campaign(self.db,'limited','Limited','ad_a',tags='main',max_cycles=3); self.activate('limited')
        enqueue_campaign(self.db,'limited',run_key='same'); enqueue_campaign(self.db,'limited',run_key='same')
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT completed_cycles FROM campaigns WHERE campaign_id='limited'").fetchone()[0],1)

    def test_scheduler_disables_after_cycle_limit(self):
        create_campaign(self.db,'limited','Limited','ad_a',tags='main',max_cycles=1); self.activate('limited')
        configure_interval(self.db,'limited',3600,'Australia/Adelaide',start_in_seconds=0)
        self.assertEqual(len(Scheduler(self.db).tick()),1)
        past=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(timespec='seconds')
        with self.db.connect() as con: con.execute("UPDATE campaign_schedules SET next_run_at=? WHERE campaign_id='limited'",(past,))
        self.assertEqual(Scheduler(self.db).tick(),[])
        with self.db.connect() as con: self.assertEqual(con.execute("SELECT enabled FROM campaign_schedules WHERE campaign_id='limited'").fetchone()[0],0)

    def test_cycle_limited_campaign_archives_after_queue_drains(self):
        create_campaign(self.db,'limited','Limited','ad_a',tags='main',max_cycles=1); self.activate('limited')
        enqueue_campaign(self.db,'limited',run_key='a')
        self.assertEqual(finalize_cycle_limited_campaigns(self.db),0)
        with self.db.connect() as con: con.execute("UPDATE queue SET status='sent' WHERE campaign_id='limited'")
        self.assertEqual(finalize_cycle_limited_campaigns(self.db),1)
        with self.db.connect() as con: self.assertEqual(con.execute("SELECT lifecycle_state FROM campaigns WHERE campaign_id='limited'").fetchone()[0],'archived')

    def test_rule_rejects_unknown_condition(self):
        with self.assertRaisesRegex(ValueError,'Unsupported rule condition'):
            upsert_rule(self.db,'r','R',{'mystery':1},{'protect':True})

    def test_rule_rejects_unknown_action(self):
        with self.assertRaisesRegex(ValueError,'Unsupported rule action'):
            upsert_rule(self.db,'r','R',{'tags_any':['main']},{'explode':True})

    def test_rule_dry_run_does_not_change_destination(self):
        upsert_rule(self.db,'r','R',{'tags_any':['main']},{'min_interval_seconds':7200})
        result=apply_rules(self.db,dry_run=True)
        self.assertEqual(result['matched'],2)
        with self.db.connect() as con: self.assertEqual(con.execute('SELECT min_interval_seconds FROM destinations WHERE group_id=-1001').fetchone()[0],0)

    def test_rule_sets_min_interval(self):
        upsert_rule(self.db,'r','R',{'tags_any':['south']},{'min_interval_seconds':7200})
        apply_rules(self.db)
        with self.db.connect() as con:
            self.assertEqual(con.execute('SELECT min_interval_seconds FROM destinations WHERE group_id=-1001').fetchone()[0],7200)
            self.assertEqual(con.execute('SELECT min_interval_seconds FROM destinations WHERE group_id=-1003').fetchone()[0],7200)

    def test_rule_preferred_account_falls_back_to_accessible(self):
        upsert_rule(self.db,'r','R',{'tags_any':['main']},{'preferred_account':'secondary'})
        apply_rules(self.db)
        with self.db.connect() as con:
            self.assertEqual(con.execute('SELECT preferred_account FROM destinations WHERE group_id=-1001').fetchone()[0],'primary')
            self.assertEqual(con.execute('SELECT preferred_account FROM destinations WHERE group_id=-1002').fetchone()[0],'secondary')

    def test_rule_never_auto_post_disables(self):
        upsert_rule(self.db,'r','R',{'tags_any':['north']},{'never_auto_post':True})
        apply_rules(self.db)
        with self.db.connect() as con: self.assertEqual(tuple(con.execute('SELECT never_auto_post,enabled FROM destinations WHERE group_id=-1002').fetchone()),(1,0))

    def test_rule_cannot_auto_enable_review_destination(self):
        upsert_rule(self.db,'r','R',{'tags_any':['new']},{'enable':True})
        apply_rules(self.db)
        with self.db.connect() as con: self.assertEqual(con.execute('SELECT enabled FROM destinations WHERE group_id=-1005').fetchone()[0],0)

    def test_rule_add_remove_tags(self):
        upsert_rule(self.db,'r','R',{'tags_any':['south']},{'add_tags':['regional'],'remove_tags':['south']})
        apply_rules(self.db)
        with self.db.connect() as con:
            tags={r[0] for r in con.execute('SELECT tag FROM destination_tags WHERE group_id=-1001').fetchall()}
        self.assertIn('regional',tags); self.assertNotIn('south',tags)

    def test_rule_quiet_hours(self):
        upsert_rule(self.db,'r','R',{'tags_any':['north']},{'quiet_start':'22:00','quiet_end':'07:00'})
        apply_rules(self.db)
        with self.db.connect() as con: self.assertEqual(tuple(con.execute('SELECT quiet_start,quiet_end FROM destinations WHERE group_id=-1002').fetchone()),('22:00','07:00'))

    def test_rules_list_priority(self):
        upsert_rule(self.db,'z','Z',{}, {'protect':True},priority=200); upsert_rule(self.db,'a','A',{}, {'protect':False},priority=10)
        self.assertEqual([r['rule_id'] for r in list_rules(self.db)],['a','z'])

    def test_uncertain_queue_generates_recommendation(self):
        self.activate(); enqueue_campaign(self.db,'camp',run_key='u')
        with self.db.connect() as con: con.execute("UPDATE queue SET status='uncertain' WHERE campaign_id='camp'")
        generate_recommendations(self.db)
        self.assertTrue(any(r['category']=='uncertain_queue' for r in list_recommendations(self.db)))

    def test_review_destination_generates_recommendation(self):
        generate_recommendations(self.db)
        self.assertTrue(any(r['category']=='destination_review' for r in list_recommendations(self.db)))

    def test_unreliable_destination_generates_recommendation(self):
        now=utcnow()
        with self.db.connect() as con:
            for i,status in enumerate(['sent','sent','failed','failed','failed']):
                con.execute("INSERT INTO queue(job_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(f'x{i}','camp',-1001,'ad_a',now,status,now,now))
        generate_recommendations(self.db)
        self.assertTrue(any(r['category']=='destination_reliability' and r['target_id']=='-1001' for r in list_recommendations(self.db)))

    def test_apply_protect_recommendation(self):
        now=utcnow()
        with self.db.connect() as con:
            for i,status in enumerate(['sent','sent','failed','failed','failed']):
                con.execute("INSERT INTO queue(job_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(f'x{i}','camp',-1001,'ad_a',now,status,now,now))
        generate_recommendations(self.db)
        rec=next(r for r in list_recommendations(self.db) if r['category']=='destination_reliability')
        apply_recommendation(self.db,rec['recommendation_id'])
        with self.db.connect() as con: self.assertEqual(con.execute('SELECT protected FROM destinations WHERE group_id=-1001').fetchone()[0],1)

    def test_dismiss_recommendation(self):
        generate_recommendations(self.db); rec=next(r for r in list_recommendations(self.db) if r['category']=='destination_review')
        dismiss_recommendation(self.db,rec['recommendation_id'])
        self.assertFalse(any(r['recommendation_id']==rec['recommendation_id'] for r in list_recommendations(self.db)))

    def test_account_imbalance_recommendation(self):
        now=utcnow()
        with self.db.connect() as con:
            for i in range(18): con.execute("INSERT INTO queue(job_key,campaign_id,group_id,content_id,account_key,due_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(f'p{i}','camp',-1001,'ad_a','primary',now,'sent',now,now))
            for i in range(2): con.execute("INSERT INTO queue(job_key,campaign_id,group_id,content_id,account_key,due_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(f's{i}','camp',-1001,'ad_a','secondary',now,'sent',now,now))
        generate_recommendations(self.db)
        self.assertTrue(any(r['category']=='account_load_balance' for r in list_recommendations(self.db)))

    def test_analytics_includes_queue_status_and_success_rate(self):
        now=utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO queue(job_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('a','camp',-1001,'ad_a',?,'sent',?,?)",(now,now,now))
            con.execute("INSERT INTO queue(job_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES('b','camp',-1001,'ad_a',?,'failed',?,?)",(now,now,now))
        a=analytics_snapshot(self.db,24)
        self.assertEqual(a['queue_status']['sent'],1); self.assertEqual(a['queue_status']['failed'],1); self.assertEqual(a['success_rate'],50.0)

    def test_daily_report_contains_v3_and_campaigns(self):
        text=daily_report_text(self.db)
        self.assertIn('SMART AUTO POSTER V3.0',text); self.assertIn('Campaigns:',text)

    def test_weekly_report_contains_accounts(self):
        self.assertIn('Accounts:',weekly_report_text(self.db))

    def test_admin_readonly_is_authorized_but_cannot_control(self):
        settings=SimpleNamespace(admin_user_ids=(1,),admin_readonly_user_ids=(2,),max_queue_size=100,max_pending_per_campaign=50,max_pending_per_destination=10)
        c=TelegramAdminController(self.db,settings,SafetyController(self.db))
        self.assertTrue(c.authorized(2)); self.assertFalse(c.can_control(2)); self.assertTrue(c.can_control(1))

    def test_admin_unknown_is_denied(self):
        settings=SimpleNamespace(admin_user_ids=(1,),admin_readonly_user_ids=(2,),max_queue_size=100,max_pending_per_campaign=50,max_pending_per_destination=10)
        c=TelegramAdminController(self.db,settings,SafetyController(self.db)); self.assertFalse(c.authorized(999))

    def test_dashboard_reports_v3(self):
        self.assertIn('SMART AUTO POSTER V3.0',dashboard_text(self.db))

    def test_dual_access_balancer_prefers_healthier_account(self):
        now=utcnow()
        with self.db.connect() as con:
            con.execute("UPDATE accounts SET health_score=50 WHERE account_key='primary'"); con.execute("UPDATE accounts SET health_score=100 WHERE account_key='secondary'")
        w=Worker(self.db,None,min_send_gap_seconds=0)
        job={'preferred_account':'both','primary_access':1,'secondary_access':1,'account_key':None}
        auth={'primary':{'authorized':True},'secondary':{'authorized':True}}
        self.assertEqual(w.choose_account(job,auth)[0],'secondary')

    def test_dual_access_balancer_uses_least_recent_when_health_equal(self):
        old=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(timespec='seconds'); recent=utcnow()
        with self.db.connect() as con:
            con.execute("UPDATE accounts SET health_score=100,last_success_at=? WHERE account_key='primary'",(recent,)); con.execute("UPDATE accounts SET health_score=100,last_success_at=? WHERE account_key='secondary'",(old,))
        w=Worker(self.db,None,min_send_gap_seconds=0); job={'preferred_account':'both','primary_access':1,'secondary_access':1,'account_key':None}; auth={'primary':{'authorized':True},'secondary':{'authorized':True}}
        self.assertEqual(w.choose_account(job,auth)[0],'secondary')

    def test_explicit_primary_affinity_still_wins(self):
        with self.db.connect() as con: con.execute("UPDATE accounts SET health_score=10 WHERE account_key='primary'")
        w=Worker(self.db,None,min_send_gap_seconds=0); job={'preferred_account':'primary','primary_access':1,'secondary_access':1,'account_key':None}; auth={'primary':{'authorized':True},'secondary':{'authorized':True}}
        self.assertEqual(w.choose_account(job,auth)[0],'primary')

    def test_control_panel_exposes_v3_collections_rules_recommendations(self):
        text=(Path(__file__).parents[1]/'CONTROL_PANEL.ps1').read_text(encoding='utf-8')
        self.assertIn('SMART AUTO POSTER V3.0',text)
        self.assertIn('62. List destination collections',text)
        self.assertIn('65. List automation rules',text)
        self.assertIn('68. Generate/list smart recommendations',text)
        self.assertIn('72. V3 release verification',text)

    def test_master_updater_contains_hash_verification_and_target_guard(self):
        text=(Path(__file__).parents[1]/'master_updater'/'APPLY_UPDATE.ps1').read_text(encoding='utf-8')
        self.assertIn('SHA-256 mismatch',text); self.assertIn('Unsafe manifest target',text); self.assertIn('not newer than installed version',text)
        self.assertIn('SQLite online backup failed before update',text); self.assertIn('Database restored automatically',text)
        rb=(Path(__file__).parents[1]/'master_updater'/'ROLLBACK_LAST_UPDATE.ps1').read_text(encoding='utf-8')
        self.assertIn('Database rollback complete',rb); self.assertIn('database_path',rb)


if __name__=='__main__': unittest.main()
