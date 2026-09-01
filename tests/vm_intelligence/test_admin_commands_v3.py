import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.integrated_schema import ensure_v3_schema
from shared.vm_intelligence.admin_commands import handle_intelligence_command

class AdminCommandV3Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
        (self.root/"bots").mkdir();(self.root/"shared").mkdir();(self.root/"diagnostics").mkdir()
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3");ensure_v3_schema(self.store)
        # cached report avoids expensive Brain rebuild for commands that do not need it
        report={
          "generated_at_utc":datetime.now(timezone.utc).isoformat(),"scorecard":{"overall":95},
          "security":{"score":98,"files_scanned":0,"findings":[]},"incidents":[],"inbox":[],
          "predictive_maintenance":[],"automation_opportunities":[],"goals":[],"meta_intelligence":{"self_health":"healthy","cycles_7d":1,"cycle_reliability_pct":100,"avg_cycle_ms":1,"max_metric_sources":6},
          "cto_priorities":[],"bot_scoreboard":[],"insights":[],"root_causes":[],"recommendations":[],"autonomy":{"level":5,"effective_level":5,"level_name":"experiment","effective_level_name":"experiment"},"reliability":{"experiment_freeze_recommended":False},"evidence_v6":{"score":100},"disaster_recovery_v6":{"latest_backup":"verified"},"capability_trust_v5":{"capabilities":[{"capability":"certified_experiment","minimum_level":5,"certification":"certified"}]},
          "efficiency":[],"capacity":{"disk_free_gib":1,"disk_total_gib":2,"known_database_mib":0,"cpu_capacity":"n/a","memory_capacity":"n/a","recommendation":"n/a"},
          "improvements":[],"lessons":[],"causal_evidence":[],"testing_intelligence":{"impact_suites":[],"regression_test_proposals":[]},"postmortems":[],"digital_twin":{"nodes":[],"edges":[],"note":"n/a"},"cost_intelligence":{"configured":False,"total_estimated_cost":None,"note":"n/a"},"integrated":{}
        }
        (self.root/"diagnostics"/"intelligence_report.json").write_text(json.dumps(report),encoding="utf-8")
    def tearDown(self):self.t.cleanup()

    def test_goal_management_commands(self):
        msg=handle_intelligence_command("goalset",["x","Smart_Auto_Poster_V2","success_rate_24h",">=","95","Keep","success"],self.root)
        self.assertIn("saved",msg)
        self.assertIn("disabled",handle_intelligence_command("goaloff",["x"],self.root))
        self.assertIn("enabled",handle_intelligence_command("goalon",["x"],self.root))

    def test_experiment_lifecycle_commands(self):
        msg=handle_intelligence_command("experimentstart",["Smart_Auto_Poster_V2","cache_ttl","90","Schedule","test"],self.root)
        self.assertIn("Experiment #",msg)
        with self.store.connect() as con:eid=con.execute("SELECT experiment_id FROM experiments").fetchone()[0]
        msg=handle_intelligence_command("experimentfinish",[str(eid),"win","96","measured"],self.root)
        self.assertIn("completed as win",msg)

if __name__=="__main__":unittest.main()
