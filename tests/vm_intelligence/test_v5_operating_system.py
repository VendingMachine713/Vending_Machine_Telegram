from __future__ import annotations
import json, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.events import Event
from shared.vm_intelligence.metrics import MetricStore
from shared.vm_intelligence.v5_schema import ensure_v5_schema
from shared.vm_intelligence.root_cause_v5 import RootCauseEngine
from shared.vm_intelligence.predictive_ops_v5 import PredictiveOperations
from shared.vm_intelligence.release_intelligence_v5 import ReleaseIntelligence
from shared.vm_intelligence.automation_discovery_v5 import AutomationDiscovery
from shared.vm_intelligence.experiment_governance_v5 import ExperimentGovernance
from shared.vm_intelligence.capability_trust_v5 import CapabilityTrust
from shared.vm_intelligence.engineering_candidate_v5 import EngineeringCandidateManager
from shared.vm_intelligence.strategic_planner_v5 import StrategicPlanner
from shared.vm_intelligence.brain import Brain

class V5OperatingSystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/"project";self.root.mkdir()
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
        ensure_v5_schema(self.store)

    def tearDown(self):self.tmp.cleanup()

    def test_v5_schema_is_version_8_and_all_control_tables_exist(self):
        with self.store.connect() as con:
            version=con.execute("SELECT value FROM intelligence_meta WHERE key='schema_version'").fetchone()[0]
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(version,"8")
        required={"incident_timelines","failure_families","predictions","release_candidates",
                  "automation_candidates","capability_trust","engineering_candidates",
                  "strategic_backlog","planner_runs"}
        self.assertTrue(required.issubset(tables))

    def test_root_cause_engine_clusters_incidents_and_correlates_nearby_events(self):
        now=datetime.now(timezone.utc)
        self.store.add_event(Event(source="VM_Guard",kind="runtime",action="restart",outcome="failure",
                                   timestamp_utc=(now-timedelta(seconds=10)).isoformat()))
        with self.store.connect() as con:
            con.execute("""INSERT INTO incidents(fingerprint,source,category,severity,title,status,first_seen_utc,last_seen_utc,occurrences,evidence_json,resolution)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              ("x","VM_Guard","runtime","high","Guard stopped","open",now.isoformat(),now.isoformat(),2,"{}",""))
        out=RootCauseEngine(self.store).analyze(24)
        self.assertEqual(len(out["failure_families"]),1)
        fam=out["failure_families"][0]
        self.assertEqual(fam["incident_count"],1)
        self.assertEqual(fam["recurrence_count"],1)
        self.assertTrue(out["timelines"][0]["events"])
        self.assertFalse(out["automatic_actions"])

    def test_predictive_operations_is_recommendation_only(self):
        now=datetime.now(timezone.utc)
        with self.store.connect() as con:
            for i,val in enumerate([0,0,1,1,2]):
                ts=(now-timedelta(hours=5-i)).isoformat()
                con.execute("""INSERT INTO bot_metrics(bucket_utc,observed_at_utc,source,metric,value,unit,quality,metadata_json)
                  VALUES(?,?,?,?,?,?,?,?)""",(ts,ts,"Smart_Auto_Poster_V2","uncertain_queue",val,"jobs","observed","{}"))
        integrated={"Smart_Auto_Poster_V2":{"metrics":{"uncertain_queue":2,"pending_queue":0}},
                    "VM_Platform":{"metrics":{"managed_services_down":0}},
                    "Universal_Search":{"metrics":{"search_errors":0}}}
        out=PredictiveOperations(self.store).forecast(integrated)
        q=next(x for x in out["predictions"] if x["metric"]=="uncertain_queue")
        self.assertEqual(q["status"],"watch")
        self.assertGreater(q["probability"],.35)
        self.assertEqual(out["execution_authority"],"recommendation_only")
        self.assertTrue(all(not x["automatic"] for x in out["maintenance"]))

    def test_release_intelligence_never_auto_promotes(self):
        dep=[{"source":"shared/vm_core/services.py","target":"VM_Guard"}]
        out=ReleaseIntelligence(self.store,self.root).gate(
            "r1",["shared/vm_core/services.py"],dep,
            baseline={"overall_score":95},observed={"overall_score":94})
        self.assertIn("VM_Guard",out["blast_radius"])
        self.assertFalse(out["automatic_promotion"])
        self.assertEqual(out["gate_status"],"reject")

    def test_automation_discovery_generates_shadow_runbook_only(self):
        for _ in range(4):
            self.store.record_decision(source="VM_Intelligence",action="restart_guard",authority="automatic",
                risk="low",confidence=.99,reason="test",outcome="success")
        out=AutomationDiscovery(self.store).discover(30)
        self.assertEqual(len(out["candidates"]),1)
        row=out["candidates"][0]
        self.assertEqual(row["status"],"shadow")
        self.assertEqual(row["runbook"]["mode"],"shadow")
        self.assertFalse(out["automatic_activation"])

    def test_l5_experiment_only_certified_domain_and_not_during_freeze(self):
        gov=ExperimentGovernance(self.store)
        self.assertFalse(gov.evaluate("cache_ttl",{"experiment_freeze_recommended":False},4)["allowed"])
        self.assertTrue(gov.evaluate("cache_ttl",{"experiment_freeze_recommended":False},5)["allowed"])
        self.assertFalse(gov.evaluate("cache_ttl",{"experiment_freeze_recommended":True},5)["allowed"])
        self.assertFalse(gov.evaluate("credentials",{"experiment_freeze_recommended":False},7)["allowed"])

    def test_capability_authority_is_earned_independently(self):
        trust=CapabilityTrust(self.store)
        before=trust.snapshot(7)
        exp=next(x for x in before["capabilities"] if x["capability"]=="certified_experiment")
        self.assertFalse(exp["allowed_at_requested_level"])
        for _ in range(20):trust.record("certified_experiment","success")
        after=trust.snapshot(7)
        exp=next(x for x in after["capabilities"] if x["capability"]=="certified_experiment")
        self.assertEqual(exp["certification"],"certified")
        self.assertTrue(exp["allowed_at_requested_level"])
        self.assertEqual(exp["effective_level"],5)
        self.assertFalse(after["global_auto_promotion"])

    def test_forbidden_capabilities_never_become_executable(self):
        trust=CapabilityTrust(self.store).snapshot(7)
        self.assertIn("direct_production_source_rewrite",trust["forbidden"])
        self.assertIn("blind_uncertain_retry",trust["forbidden"])

    def test_isolated_engineering_candidate_has_zero_production_mutation(self):
        mgr=EngineeringCandidateManager(self.store,self.root)
        row=mgr.propose("Fix runtime drift","VM_Guard","test_runtime_drift","one-file candidate patch")
        self.assertFalse(row["production_mutation"])
        self.assertEqual(row["execution_mode"],"isolated_only")
        db=mgr.list()[0]
        self.assertEqual(db["production_mutation"],0)
        self.assertIn("engineering_worktrees",db["workspace"])

    def test_l7_planner_does_not_grant_blanket_l7_execution(self):
        trust=CapabilityTrust(self.store)
        # Planner can plan at L7, but no capabilities are certified yet.
        caps=trust.snapshot(7)
        snapshot={"scorecard":{"overall":97},"platform_drift":{"counts":{"high":1,"medium":0},"score":80},
                  "reliability":{"breaches":0,"historical":{"error_budgets_exhausted":0,"max_burn_rate":0}},
                  "predictive_v5":{"predictions":[]},"automation_discovery_v5":{"candidates":[]},
                  "engineering_v5":[],"attention_budget":{"automatic_decisions":1,"estimated_minutes_saved":5}}
        plan=StrategicPlanner(self.store).compile(snapshot,[],caps)
        self.assertEqual(plan["planner_level"],7)
        self.assertEqual(plan["execution_authority"],"capability_specific")
        self.assertFalse(plan["global_production_execution"])
        self.assertGreater(plan["blocked_count"],0)

    def test_certified_capability_can_make_matching_plan_executable_without_global_promotion(self):
        trust=CapabilityTrust(self.store)
        for _ in range(20):trust.record("managed_restart","success")
        caps=trust.snapshot(7)
        snapshot={"scorecard":{"overall":90},"platform_drift":{"counts":{"high":0,"medium":0},"score":100},
                  "reliability":{"breaches":1,"historical":{"error_budgets_exhausted":1,"max_burn_rate":3}},
                  "predictive_v5":{"predictions":[]},"automation_discovery_v5":{"candidates":[]},
                  "engineering_v5":[],"attention_budget":{"automatic_decisions":0,"estimated_minutes_saved":0}}
        plan=StrategicPlanner(self.store).compile(snapshot,[],caps)
        p0=plan["backlog"][0]
        self.assertEqual(p0["action_key"],"managed_restart")
        self.assertTrue(p0["allowed"])
        self.assertFalse(plan["global_production_execution"])

    def test_brain_snapshot_exposes_full_v5_stack(self):
        snap=Brain(self.store,self.root).executive_snapshot(24)
        for key in ("root_cause_v5","predictive_v5","release_intelligence_v5",
                    "automation_discovery_v5","capability_trust_v5","engineering_v5",
                    "strategic_planner_v5"):
            self.assertIn(key,snap)
        self.assertEqual(snap["strategic_planner_v5"]["planner_level"],7)
        self.assertFalse(snap["strategic_planner_v5"]["global_production_execution"])

if __name__=="__main__":
    unittest.main()
