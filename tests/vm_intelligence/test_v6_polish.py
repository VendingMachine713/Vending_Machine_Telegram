from __future__ import annotations
import json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.policy_kernel_v6 import PolicyKernel
from shared.vm_intelligence.evidence_truth_v6 import EvidenceTruthLayer
from shared.vm_intelligence.prediction_calibration_v6 import PredictionCalibration
from shared.vm_intelligence.runbook_factory_v6 import RunbookFactory
from shared.vm_intelligence.disaster_recovery_v6 import DisasterRecoveryController
from shared.vm_intelligence.strategic_operator_v6 import StrategicOperator
from shared.vm_intelligence.intervention_learning_v6 import InterventionLearning
from shared.vm_intelligence.v6_schema import ensure_v6_schema

class V6PolishTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'project';self.root.mkdir()
        self.store=IntelligenceStore(self.root/'state'/'vm_intelligence.sqlite3');ensure_v6_schema(self.store)
    def tearDown(self):self.tmp.cleanup()

    def test_policy_preview_does_not_pollute_decision_history(self):
        k=PolicyKernel(self.store)
        r=k.evaluate(action_key='managed_restart',capability='managed_restart',requested_level=7,effective_level=4,
            capability_record={'minimum_level':4,'certification':'certified'},risk='low',evidence_quality=100,
            rollback_ready=True,backup_ready=True,security_score=100,reliability_freeze=False,record=False)
        self.assertEqual(r['decision'],'ALLOW');self.assertFalse(r['recorded'])
        with self.store.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM policy_decisions').fetchone()[0],0)
        k.evaluate(action_key='managed_restart',capability='managed_restart',requested_level=4,effective_level=4,
            capability_record={'minimum_level':4,'certification':'certified'},risk='low',evidence_quality=100,
            rollback_ready=True,backup_ready=True,security_score=100,reliability_freeze=False,record=True)
        with self.store.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM policy_decisions').fetchone()[0],1)

    def test_evidence_quality_has_grade_coverage_and_authority_cap(self):
        now=datetime.now(timezone.utc)
        integrated={'A':{'observed_at_utc':now.isoformat(),'evidence':['direct'],'metrics':{'x':1}},
                    'B':{'observed_at_utc':(now-timedelta(hours=2)).isoformat(),'metrics':{'y':1}}}
        out=EvidenceTruthLayer(self.store).assess(integrated,now.isoformat())
        self.assertIn(out['grade'],{'A','B','C','D','F'});self.assertEqual(out['coverage_pct'],50.0)
        self.assertIn(out['authority_cap'],{'normal','recommend_only','observe_only'})

    def test_prediction_calibration_reports_maturity_not_false_confidence(self):
        out=PredictionCalibration(self.store).evaluate_due()
        self.assertEqual(out['maturity'],'insufficient_evidence');self.assertEqual(out['resolved_total'],0)
        self.assertFalse(out['automatic_authority_from_prediction_accuracy'])

    def test_runbook_requires_simulation_shadow_and_trust_before_certification(self):
        f=RunbookFactory(self.store)
        out=f.refresh([{'candidate_key':'abc','runbook':{'trigger':'x','actions':['restart']}}],[])
        key=out['created'][0]['runbook_key'];self.assertEqual(out['revisions'][0]['status'],'DRAFT')
        self.assertTrue(f.record_validation(key,1,simulation_status='passed',evidence={'simulation':'ok'}))
        out=f.refresh([],[]);row=next(x for x in out['revisions'] if x['runbook_key']==key)
        self.assertEqual(row['status'],'SIMULATED')
        f.record_validation(key,1,shadow_status='passed',evidence={'shadow':'ok'})
        trust=[{'runbook_key':key,'attempts':20,'trust_score':98,'certification':'certified'}]
        out=f.refresh([],trust);row=next(x for x in out['revisions'] if x['runbook_key']==key)
        self.assertEqual(row['status'],'CERTIFIED_L4');self.assertTrue(row['certification_ready'])
        self.assertFalse(out['automatic_certification'])

    def test_failed_runbook_validation_revokes_candidate(self):
        f=RunbookFactory(self.store);key=f.refresh([{'candidate_key':'bad','runbook':{}}],[])['created'][0]['runbook_key']
        f.record_validation(key,1,simulation_status='failed')
        row=next(x for x in f.refresh([],[])['revisions'] if x['runbook_key']==key)
        self.assertEqual(row['status'],'REVOKED')

    def test_dr_confidence_decays_and_drill_becomes_due(self):
        (self.root/'backups').mkdir();(self.root/'backups'/'b1').mkdir()
        old=(datetime.now(timezone.utc)-timedelta(days=60)).isoformat()
        with self.store.connect() as con:
            con.execute('''INSERT INTO disaster_recovery_drills(started_at_utc,completed_at_utc,mode,backup_age_minutes,rpo_minutes,rto_seconds,integrity_ok,restore_verified,confidence,outcome,evidence_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(old,old,'simulation',10,10,120,1,1,.95,'passed','{}'))
        d=DisasterRecoveryController(self.store,self.root).snapshot()
        self.assertTrue(d['drill_due']);self.assertLess(d['restore_confidence_pct'],95.0)
        self.assertGreater(d['last_verified_restore_age_days'],30)

    def test_strategic_operator_marks_policy_allowed_and_blocked_items(self):
        planner={'backlog':[{'priority':'P0','title':'recover','action_key':'managed_restart'},
                            {'priority':'P1','title':'optimise','action_key':'bounded_optimisation'}]}
        previews=[{'action_key':'managed_restart','decision':'ALLOW','reasons':['ok']},
                  {'action_key':'bounded_optimisation','decision':'REQUIRE_APPROVAL','reasons':['uncertified']}]
        out=StrategicOperator(self.store).build(planner,{'evidence_quality':95,'security_score':100,'reliability_freeze':False},previews)
        self.assertEqual(out['executable_items'],1);self.assertEqual(out['blocked_or_deferred_items'],1)
        now=out['horizons']['NOW'][0];self.assertTrue(now['execution_allowed']);self.assertEqual(now['policy_decision'],'ALLOW')

    def test_intervention_matures_root_cause_success_after_seven_days(self):
        old=datetime.now(timezone.utc)-timedelta(days=8)
        with self.store.connect() as con:
            con.execute('''INSERT INTO intervention_outcomes(action_key,source,started_at_utc,completed_at_utc,immediate_success,recurrence_24h,recurrence_7d,root_cause_success,attention_saved_minutes,outcome,evidence_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)''',('managed_restart','VM_Guard',old.isoformat(),old.isoformat(),1,None,None,None,3,'executed','{}'))
        out=InterventionLearning(self.store).summarize();row=out['actions'][0]
        self.assertEqual(row['immediate_success_pct'],100);self.assertEqual(row['recurrence_7d_pct'],0);self.assertEqual(row['root_cause_success_pct'],100)

if __name__=='__main__':unittest.main()
