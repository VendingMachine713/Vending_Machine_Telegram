import json,sys,tempfile,types,unittest
from pathlib import Path
from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.integrated_schema import ensure_v3_schema
from shared.vm_intelligence.self_heal import SelfHealingController
from shared.vm_intelligence.admin_commands import handle_intelligence_command

class V6PolicyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
        (self.root/'bots').mkdir();(self.root/'shared').mkdir();(self.root/'diagnostics').mkdir()
        self.store=IntelligenceStore(self.root/'state'/'vm_intelligence.sqlite3');ensure_v3_schema(self.store)
    def tearDown(self):self.t.cleanup()
    def _managed_admin_down(self):
        bot=self.root/'bots'/'Admin_Command_Centre';bot.mkdir(parents=True)
        (bot/'main.py').write_text("print('ok')\n",encoding='utf-8')
        (bot/'BOT_MANIFEST.json').write_text(json.dumps({'name':'Admin_Command_Centre','entrypoint':'main.py','classification':'CANONICAL','entrypoint_confidence':'high','lifecycle':{'auto_start':True,'auto_restart':True}}),encoding='utf-8')
        (self.root/'diagnostics'/'live_runtime.json').write_text(json.dumps({'services':[{'name':'Admin_Command_Centre','process_alive':False}]}),encoding='utf-8')
    def test_low_security_blocks_legacy_approved_recovery(self):
        self._managed_admin_down();calls=[]
        (self.root/'diagnostics'/'intelligence_report.json').write_text(json.dumps({'security':{'score':50},'reliability':{'experiment_freeze_recommended':False}}),encoding='utf-8')
        vm_core=types.ModuleType('shared.vm_core');supervisor=types.ModuleType('shared.vm_core.supervisor')
        supervisor.supervise_once=lambda *a,**k:calls.append(True)
        oldc=sys.modules.get('shared.vm_core');olds=sys.modules.get('shared.vm_core.supervisor')
        sys.modules['shared.vm_core']=vm_core;sys.modules['shared.vm_core.supervisor']=supervisor
        try:
            self.assertEqual(SelfHealingController(self.store,self.root).run(),[])
            self.assertEqual(calls,[])
            with self.store.connect() as con:
                row=con.execute("SELECT outcome,reason FROM decisions ORDER BY decision_id DESC LIMIT 1").fetchone()
            self.assertEqual(row['outcome'],'deferred');self.assertIn('security_score_below_70',row['reason'])
        finally:
            if oldc is None:sys.modules.pop('shared.vm_core',None)
            else:sys.modules['shared.vm_core']=oldc
            if olds is None:sys.modules.pop('shared.vm_core.supervisor',None)
            else:sys.modules['shared.vm_core.supervisor']=olds
    def test_experiment_requires_v6_kernel_after_domain_governance(self):
        report={'generated_at_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'scorecard':{'overall':95},'security':{'score':50},
          'incidents':[],'inbox':[],'predictive_maintenance':[],'automation_opportunities':[],'goals':[],
          'meta_intelligence':{'self_health':'healthy'},'cto_priorities':[],'autonomy':{'level':5,'effective_level':5},
          'reliability':{'experiment_freeze_recommended':False},'evidence_v6':{'score':100},
          'disaster_recovery_v6':{'latest_backup':'verified'},
          'capability_trust_v5':{'capabilities':[{'capability':'certified_experiment','minimum_level':5,'certification':'certified'}]}}
        (self.root/'diagnostics'/'intelligence_report.json').write_text(json.dumps(report),encoding='utf-8')
        msg=handle_intelligence_command('experimentstart',['A','cache_ttl','10','candidate'],self.root)
        self.assertIn('blocked by v6 policy kernel',msg);self.assertIn('security_score_below_70',msg)

if __name__=='__main__':unittest.main()
