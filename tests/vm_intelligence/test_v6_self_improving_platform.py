from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.v6_schema import ensure_v6_schema
from shared.vm_intelligence.evidence_truth_v6 import EvidenceTruthLayer
from shared.vm_intelligence.policy_kernel_v6 import PolicyKernel
from shared.vm_intelligence.runbook_factory_v6 import RunbookFactory
from shared.vm_intelligence.intervention_learning_v6 import InterventionLearning
from shared.vm_intelligence.disaster_recovery_v6 import DisasterRecoveryController
from shared.vm_intelligence.architecture_modernization_v6 import ArchitectureModernizer
from shared.vm_intelligence.strategic_operator_v6 import StrategicOperator
from shared.vm_intelligence.brain import Brain
from shared.vm_intelligence.reporting import build_report,write_report
from shared.vm_intelligence.doctor import run_doctor

class V6SelfImprovingPlatformTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'project';self.root.mkdir()
        (self.root/'state').mkdir();(self.root/'config').mkdir()
        (self.root/'config'/'vm_intelligence.json').write_text('{}',encoding='utf-8')
        self.store=IntelligenceStore(self.root/'state'/'vm_intelligence.sqlite3');ensure_v6_schema(self.store)
    def tearDown(self):self.tmp.cleanup()

    def test_schema_v12_and_control_tables(self):
        with self.store.connect() as con:
            v=con.execute("SELECT value FROM intelligence_meta WHERE key='schema_version'").fetchone()[0]
            tables={x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(v,'12')
        for t in {'evidence_records','policy_decisions','intervention_outcomes','runbook_revisions','prediction_outcomes','attention_events','disaster_recovery_drills','architecture_modernization_candidates','strategic_horizons'}:
            self.assertIn(t,tables)

    def test_evidence_quality_distinguishes_stale_from_live(self):
        now=datetime.now(timezone.utc)
        integrated={'A':{'observed_at_utc':now.isoformat(),'evidence':['direct'],'metrics':{'alive':1}},
                    'B':{'observed_at_utc':(now-timedelta(hours=2)).isoformat(),'metrics':{'latency':1}}}
        out=EvidenceTruthLayer(self.store).assess(integrated,now.isoformat())
        a=next(x for x in out['records'] if x['source']=='A');b=next(x for x in out['records'] if x['source']=='B')
        self.assertEqual(a['freshness'],'LIVE');self.assertEqual(b['freshness'],'STALE')
        self.assertGreater(a['confidence'],b['confidence']);self.assertEqual(out['stale_or_invalid'],1)

    def test_policy_kernel_permanently_denies_dangerous_actions(self):
        k=PolicyKernel(self.store)
        for action in ('blind_uncertain_retry','direct_production_source_rewrite','credential_change','permission_change','irreversible_migration'):
            r=k.evaluate(action_key=action,capability=action,requested_level=7,effective_level=7,
                capability_record={'minimum_level':7,'certification':'certified'},risk='low',evidence_quality=100,
                rollback_ready=True,backup_ready=True,security_score=100,reliability_freeze=False)
            self.assertEqual(r['decision'],'DENY')

    def test_policy_kernel_l7_planning_does_not_grant_uncertified_l6_execution(self):
        r=PolicyKernel(self.store).evaluate(action_key='bounded_optimisation',capability='bounded_optimisation',
            requested_level=7,effective_level=6,capability_record={'minimum_level':6,'certification':'unproven'},
            risk='low',evidence_quality=95,rollback_ready=True,backup_ready=True,security_score=100,reliability_freeze=False)
        self.assertEqual(r['decision'],'REQUIRE_APPROVAL')

    def test_policy_kernel_degrades_on_bad_evidence_or_security(self):
        k=PolicyKernel(self.store)
        low=k.evaluate(action_key='managed_restart',capability='managed_restart',requested_level=4,effective_level=4,
            capability_record={'minimum_level':4,'certification':'certified'},risk='low',evidence_quality=40,
            rollback_ready=True,backup_ready=True,security_score=100,reliability_freeze=False)
        sec=k.evaluate(action_key='managed_restart',capability='managed_restart',requested_level=4,effective_level=4,
            capability_record={'minimum_level':4,'certification':'certified'},risk='low',evidence_quality=100,
            rollback_ready=True,backup_ready=True,security_score=60,reliability_freeze=False)
        self.assertEqual(low['decision'],'DEFER');self.assertEqual(sec['decision'],'DEFER')

    def test_runbook_factory_creates_draft_only(self):
        c={'candidate_key':'abc','runbook':{'trigger':'x','actions':['restart']}}
        out=RunbookFactory(self.store).refresh([c],[])
        self.assertEqual(out['created'][0]['status'],'DRAFT');self.assertFalse(out['automatic_certification'])
        self.assertEqual(out['revisions'][0]['simulation_status'],'pending')

    def test_intervention_learning_separates_recovery_from_root_cause_success(self):
        now=datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            con.execute("INSERT INTO intervention_outcomes(action_key,source,started_at_utc,completed_at_utc,immediate_success,recurrence_7d,root_cause_success,attention_saved_minutes,outcome) VALUES(?,?,?,?,?,?,?,?,?)",
                ('restart_admin','Admin',now,now,1,1,0,5,'recovered'))
        x=InterventionLearning(self.store).summarize()['actions'][0]
        self.assertEqual(x['immediate_success_pct'],100);self.assertEqual(x['root_cause_success_pct'],0);self.assertEqual(x['recurrence_7d_pct'],100)

    def test_disaster_recovery_never_claims_restore_confidence_without_drill(self):
        (self.root/'backups').mkdir();(self.root/'backups'/'one').mkdir()
        d=DisasterRecoveryController(self.store,self.root).snapshot()
        self.assertEqual(d['restore_confidence_pct'],0);self.assertTrue(d['drill_due']);self.assertFalse(d['automatic_destructive_restore'])

    def test_architecture_modernization_remains_isolated_proposal(self):
        norm={'violations':[{'service':'Admin','category':'compatibility_bridge_active'}]}
        out=ArchitectureModernizer(self.store).propose(norm,[])
        self.assertEqual(len(out['candidates']),1);self.assertTrue(out['candidates'][0]['isolated_only']);self.assertFalse(out['candidates'][0]['production_mutation']);self.assertFalse(out['automatic_migration'])

    def test_strategic_operator_builds_multiple_horizons(self):
        planner={'backlog':[{'priority':'P0','title':'now'},{'priority':'P1','title':'soon'},{'priority':'P2','title':'later'}]}
        out=StrategicOperator(self.store).build(planner,{})
        self.assertEqual(out['planner_level'],7);self.assertIn('NOW',out['horizons']);self.assertIn('QUARTER',out['horizons'])
        self.assertEqual(out['execution_authority'],'policy_kernel_and_capability_specific')

    def test_brain_exposes_v6_closed_loop_surfaces(self):
        snap=Brain(self.store,self.root).executive_snapshot(24)
        for k in ('evidence_v6','policy_kernel_v6','prediction_calibration_v6','intervention_learning_v6','runbook_factory_v6','attention_governor_v6','disaster_recovery_v6','architecture_modernization_v6','strategic_operator_v6'):
            self.assertIn(k,snap)
        self.assertEqual(snap['strategic_operator_v6']['planner_level'],7)

    def test_report_and_doctor_include_v6_surfaces(self):
        r=build_report(self.store,hours=24,root=self.root);self.assertEqual(r['schema_version'],12)
        write_report(r,self.root/'diagnostics')
        for n in ('intelligence_evidence_v6.json','intelligence_policy_kernel_v6.json','intelligence_strategic_operator_v6.json','intelligence_disaster_recovery_v6.json'):
            self.assertTrue((self.root/'diagnostics'/n).is_file())
        d=run_doctor(self.root);checks={x['check']:x for x in d['checks']}
        self.assertTrue(checks['schema_version']['ok']);self.assertEqual(str(checks['schema_version']['detail']),'12')
        self.assertTrue(checks['v6_evidence_truth']['ok']);self.assertTrue(checks['v6_policy_kernel']['ok']);self.assertTrue(checks['v6_strategic_operator']['ok'])

if __name__=='__main__':unittest.main()
