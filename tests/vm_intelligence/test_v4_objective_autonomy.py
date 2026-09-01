from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.v4_schema import ensure_v4_schema
from shared.vm_intelligence.runtime_registry import RuntimeRegistry
from shared.vm_intelligence.platform_normalization import PlatformNormalizer
from shared.vm_intelligence.reliability import ReliabilityBrain
from shared.vm_intelligence.autonomy import AutonomyController
from shared.vm_intelligence.objectives import ObjectiveEngine
from shared.vm_intelligence.dependency_graph import DependencyGraph
from shared.vm_intelligence.release_gate import ReleaseGate
from shared.vm_intelligence.attention_budget import AttentionBudget
from shared.vm_intelligence.brain import Brain


class V4ObjectiveAutonomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/"bots").mkdir()
        (self.root/"diagnostics").mkdir()
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
        ensure_v4_schema(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def make_bot(self,name,depth=2,managed=True):
        bot=self.root/"bots"/name
        runtime=bot
        for _ in range(depth): runtime=runtime/name
        runtime.mkdir(parents=True)
        (runtime/"main.py").write_text("from shared.vm_core.services import service_status\n",encoding="utf-8")
        (runtime/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":name,"classification":"CANONICAL","entrypoint":"main.py","entrypoint_confidence":"high",
            "lifecycle":{"auto_start":managed,"auto_restart":managed},"version":"1.0"
        }),encoding="utf-8")
        return bot,runtime

    def test_v4_schema_tables(self):
        with self.store.connect() as con:
            names={r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        expected={"runtime_registry","architecture_violations","slo_definitions","slo_evaluations",
                  "operational_objectives","objective_evaluations","autonomy_state","action_registry",
                  "runbook_executions","dependency_edges","release_acceptance","attention_metrics"}
        self.assertTrue(expected.issubset(names))

    def test_runtime_registry_discovers_nested_canonical(self):
        _,runtime=self.make_bot("Admin_Command_Centre",depth=2)
        rows=RuntimeRegistry(self.store,self.root).refresh()
        row=next(x for x in rows if x["service"]=="Admin_Command_Centre")
        self.assertEqual(Path(row["canonical_root"]),runtime.resolve())
        self.assertTrue(row["managed"])
        self.assertGreaterEqual(row["nested_depth"],2)
        self.assertTrue((self.root/"state"/"runtime_registry.json").is_file())


    def test_runtime_registry_keeps_bridge_as_compatibility_not_canonical(self):
        bot,runtime=self.make_bot("Admin_Command_Centre",depth=2,managed=True)
        root_main=bot/"main.py"
        root_main.write_text("# VM_INTELLIGENCE_RUNTIME_BRIDGE_V307\n",encoding="utf-8")
        bridge={
            "services":[{
                "bot":"Admin_Command_Centre",
                "root_main":str(root_main.resolve()),
                "nested":{
                    "entrypoint_abs":str((runtime/"main.py").resolve()),
                    "manifest":str((runtime/"BOT_MANIFEST.json").resolve()),
                },
                "policy":{"auto_start":True,"auto_restart":True},
            }]
        }
        state=self.root/"state";state.mkdir(exist_ok=True)
        (state/"runtime_bridge.json").write_text(json.dumps(bridge),encoding="utf-8")
        rows=RuntimeRegistry(self.store,self.root).refresh()
        row=next(x for x in rows if x["service"]=="Admin_Command_Centre")
        self.assertEqual(Path(row["canonical_entrypoint"]),(runtime/"main.py").resolve())
        self.assertEqual(Path(row["compatibility_entrypoint"]),root_main.resolve())
        self.assertNotEqual(Path(row["canonical_entrypoint"]),Path(row["compatibility_entrypoint"]))
        self.assertTrue(row["managed"])

    def test_platform_normalizer_is_proposal_only(self):
        self.make_bot("VM_Guard",depth=2)
        reg=RuntimeRegistry(self.store,self.root).refresh()
        result=PlatformNormalizer(self.store,self.root).refresh(reg)
        self.assertFalse(result["automatic_relocation"])
        self.assertTrue(any(x["category"]=="deep_nested_runtime" for x in result["violations"]))
        self.assertTrue(all(x["automatic"] is False for x in result["normalization_plan"]))

    def test_reliability_slo_and_error_budget(self):
        result=ReliabilityBrain(self.store).evaluate({
            "VM_Intelligence":{"overall_score":95,"latest_backup_integrity":1},
            "Smart_Auto_Poster_V2":{"success_rate_24h":97,"uncertain_queue":0},
            "Admin_Command_Centre":{"process_alive":1},
            "VM_Guard":{"process_alive":1},
            "VM_Platform":{"managed_services_down":0},
        })
        sap=next(x for x in result["slos"] if x["slo_key"]=="sap_delivery_success")
        self.assertEqual(sap["status"],"breached")
        self.assertEqual(sap["error_budget_remaining_pct"],50.0)
        self.assertGreaterEqual(result["breaches"],1)

    def test_autonomy_ladder_blocks_high_level_actions(self):
        ctl=AutonomyController(self.store)
        self.assertTrue(ctl.allowed("restart_unhealthy_process")["allowed"])
        self.assertFalse(ctl.allowed("start_guarded_experiment")["allowed"])
        ctl.set_level(5,"test")
        self.assertTrue(ctl.allowed("start_guarded_experiment",risk="medium",backup_available=True)["allowed"])
        self.assertFalse(ctl.allowed("adjust_low_risk_config",backup_available=True)["allowed"])

    def test_safe_mode_caps_effective_autonomy_and_blocks_experiments(self):
        ctl=AutonomyController(self.store)
        ctl.set_level(7,"test objective mode")
        ctl.freeze(1,"test safe mode")
        eff=ctl.effective_level(False)
        self.assertEqual(eff["requested_level"],7)
        self.assertEqual(eff["effective_level"],4)
        self.assertFalse(ctl.allowed("start_guarded_experiment",risk="medium",backup_available=True)["allowed"])
        ctl.unfreeze()
        self.assertTrue(ctl.allowed("start_guarded_experiment",risk="medium",backup_available=True)["allowed"])

    def test_objective_engine_generates_bounded_plan(self):
        rows=ObjectiveEngine(self.store).evaluate({
            "critical_incidents":1,"managed_services_down":1,"backup_integrity":0,
            "security_score":95,"noise_ratio":0.0,
        })
        health=next(x for x in rows if x["objective_key"]=="healthy_platform")
        self.assertEqual(health["status"],"at_risk")
        actions={x["action"] for x in health["plan"]}
        self.assertIn("gather_diagnostics",actions)
        self.assertIn("restart_unhealthy_process",actions)
        self.assertIn("runtime_bridge_recovery",actions)
        self.assertIn("create_verified_backup",actions)
        self.assertNotIn("delete",json.dumps(health).lower())


    def test_objective_plan_is_bound_to_registered_actions_and_fail_closed(self):
        engine=ObjectiveEngine(self.store)
        raw=engine.evaluate({
            "critical_incidents":1,"managed_services_down":1,"backup_integrity":0,
            "security_score":70,"noise_ratio":0.5,
        })
        ctl=AutonomyController(self.store)
        bound=engine.bind_authority(raw,ctl,backup_available=False,reliability_freeze=True)
        steps=[step for obj in bound for step in obj["plan"]]
        self.assertTrue(steps)
        self.assertTrue(all(step["policy_reason"] != "action_not_registered" for step in steps))
        actions={step["action"]:step for step in steps}
        self.assertTrue(actions["gather_diagnostics"]["allowed"])
        self.assertTrue(actions["runtime_bridge_recovery"]["allowed"])
        self.assertTrue(actions["enter_safe_mode"]["allowed"])
        self.assertFalse(actions["adjust_low_risk_config"]["allowed"])
        self.assertEqual(actions["adjust_low_risk_config"]["policy_reason"],"reliability_freeze")

    def test_dependency_graph_and_impact(self):
        self.make_bot("VM_Guard",depth=1)
        graph=DependencyGraph(self.store,self.root)
        edges=graph.build()
        self.assertTrue(any(x["target"]=="VM_Guard" and x["source"]=="shared.vm_core.services" for x in edges))
        impact=graph.impact(["shared/vm_core/services.py"])
        self.assertIn("VM_Guard",impact["services"])

    def test_release_gate_rejects_regression(self):
        result=ReleaseGate(self.store).evaluate("VM_Guard","2.0",95,89,0,0)
        self.assertEqual(result["decision"],"reject")
        self.assertIn("score_regression_gt_3",result["reasons"])

    def test_attention_budget_counts_feedback_and_automatic_decisions(self):
        now="2026-09-01T00:00:00+00:00"
        with self.store.connect() as con:
            con.execute("INSERT INTO incidents(fingerprint,source,category,severity,title,first_seen_utc,last_seen_utc) VALUES('x','VM','t','low','x',?,?)",(now,now))
            iid=con.execute("SELECT incident_id FROM incidents WHERE fingerprint='x'").fetchone()[0]
            con.execute("INSERT INTO intelligence_feedback(incident_id,verdict,details,created_at_utc) VALUES(?,?,?,?)",(iid,"useful","",now))
            con.execute("INSERT INTO decisions(source,action,authority,risk,confidence,reason,outcome,metadata_json,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                        ("VM","restart_unhealthy_process","automatic","low",.98,"test","executed","{}",now))
        a=AttentionBudget(self.store).snapshot()
        self.assertEqual(a["useful"],1)
        self.assertEqual(a["automatic_decisions"],1)
        self.assertGreater(a["estimated_minutes_saved"],0)


    def test_bridge_aware_brain_uses_canonical_source_and_avoids_false_managed_down(self):
        admin_bot,admin_runtime=self.make_bot("Admin_Command_Centre",depth=2,managed=True)
        guard_bot,guard_runtime=self.make_bot("VM_Guard",depth=2,managed=True)
        search_bot,search_runtime=self.make_bot("Universal_Search",depth=2,managed=True)
        state=self.root/"state";state.mkdir(exist_ok=True)
        bridge={"services":[]}
        bridge_status={"services":[]}
        for name,bot,runtime in (
            ("Admin_Command_Centre",admin_bot,admin_runtime),
            ("VM_Guard",guard_bot,guard_runtime),
            ("Universal_Search",search_bot,search_runtime),
        ):
            shim=bot/"main.py";shim.write_text("# VM_INTELLIGENCE_RUNTIME_BRIDGE_V307\n",encoding="utf-8")
            bridge["services"].append({
                "bot":name,"root_main":str(shim.resolve()),"desired_running":True,
                "nested":{"entrypoint_abs":str((runtime/"main.py").resolve()),
                          "manifest":str((runtime/"BOT_MANIFEST.json").resolve())},
                "policy":{"auto_start":True,"auto_restart":True},
            })
            bridge_status["services"].append({
                "bot":name,"desired_running":True,"action":"already_running",
                "status":{"alive":True,"pid":1000+len(bridge_status["services"])},
            })
        (state/"runtime_bridge.json").write_text(json.dumps(bridge),encoding="utf-8")
        (self.root/"diagnostics"/"runtime_bridge_status.json").write_text(json.dumps(bridge_status),encoding="utf-8")
        # Simulate stale recovered VM Core status saying the managed services are stopped.
        live={"services":[
            {"name":"Admin_Command_Centre","process_alive":False,"runtime_status":"STOPPED"},
            {"name":"VM_Guard","process_alive":False,"runtime_status":"STOPPED"},
            {"name":"Universal_Search","process_alive":False,"runtime_status":"STOPPED"},
        ],"components":{},"open_alerts":[]}
        validation={
            "critical_tests_ok":True,"all_test_suites_ok":True,"preflight_ok":True,"bots_runnable":3,
            "failed_test_suites":[],
            "supervisor_actions":[
                {"service":"Admin_Command_Centre","policy":{"auto_start":True,"auto_restart":True}},
                {"service":"VM_Guard","policy":{"auto_start":True,"auto_restart":True}},
                {"service":"Universal_Search","policy":{"auto_start":True,"auto_restart":True}},
            ],
        }
        (self.root/"diagnostics"/"live_runtime.json").write_text(json.dumps(live),encoding="utf-8")
        (self.root/"diagnostics"/"full_validation.json").write_text(json.dumps(validation),encoding="utf-8")
        snap=Brain(self.store,self.root).executive_snapshot()
        registry={x["service"]:x for x in snap["runtime_registry"]}
        self.assertEqual(Path(registry["Admin_Command_Centre"]["canonical_entrypoint"]),(admin_runtime/"main.py").resolve())
        self.assertEqual(Path(registry["Admin_Command_Centre"]["compatibility_entrypoint"]),(admin_bot/"main.py").resolve())
        self.assertEqual(snap["integrated"]["Admin_Command_Centre"]["metrics"]["process_alive"],1)
        self.assertEqual(snap["integrated"]["VM_Guard"]["metrics"]["process_alive"],1)
        self.assertEqual(snap["integrated"]["VM_Platform"]["metrics"]["managed_services_down"],0)
        self.assertNotIn("managed_service_down",{x["category"] for x in snap["incidents"]})
        admin_slo=next(x for x in snap["reliability"]["slos"] if x["slo_key"]=="admin_available")
        guard_slo=next(x for x in snap["reliability"]["slos"] if x["slo_key"]=="guard_available")
        self.assertEqual(admin_slo["status"],"met")
        self.assertEqual(guard_slo["status"],"met")

    def test_brain_snapshot_contains_v4_surfaces(self):
        # Minimal diagnostics keep adapters fail-open while still exercising the v4 surfaces.
        (self.root/"diagnostics"/"live_runtime.json").write_text(json.dumps({"services":[],"components":{},"open_alerts":[]}),encoding="utf-8")
        (self.root/"diagnostics"/"full_validation.json").write_text(json.dumps({"critical_tests_ok":True,"all_test_suites_ok":True,"preflight_ok":True,"bots_runnable":0,"failed_test_suites":[]}),encoding="utf-8")
        snap=Brain(self.store,self.root).executive_snapshot()
        for key in ("runtime_registry","platform_normalization","reliability","objectives","autonomy","runbooks","attention_budget","dependency_graph","release_gate"):
            self.assertIn(key,snap)
        self.assertEqual(snap["autonomy"]["level"],4)


if __name__=="__main__":
    unittest.main()
