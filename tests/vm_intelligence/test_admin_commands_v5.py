from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch

from shared.vm_intelligence.admin_commands import COMMANDS,handle_intelligence_command

class AdminCommandsV5Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.snapshot={
            "generated_at_utc":datetime.now(timezone.utc).isoformat(),
            "scorecard":{"overall":98},"security":{"score":100},"incidents":[],"inbox":[],
            "predictive_maintenance":[],"automation_opportunities":[],"goals":[],"meta_intelligence":{"self_health":"healthy"},
            "cto_priorities":[],"strategic_planner_v5":{"planner_level":7,"executable_count":1,"blocked_count":2,
                "backlog":[{"priority":"P0","allowed":True,"title":"Recover Guard","action_key":"managed_restart","authority_required":4}]},
            "predictive_v5":{"predictions":[{"status":"watch","source":"Universal_Search","metric":"search_errors",
                "current":1,"predicted_value":2,"probability":.6,"confidence":.8}]},
            "automation_discovery_v5":{"candidates":[{"frequency":4,"title":"Automate restart","estimated_minutes_saved":10,
                "risk":"low","confidence":.9}]},
            "capability_trust_v5":{"capabilities":[{"capability":"managed_restart","certification":"certified",
                "trust_score":99,"effective_level":4,"attempts":20}],"forbidden":[]},
            "root_cause_v5":{"failure_families":[{"source":"VM_Guard","title":"Guard stopped","incident_count":2,"recurrence_count":1}]},
            "engineering_v5":[{"candidate_key":"abc","title":"Fix Guard","targeted_status":"passed","full_status":"pending",
                "security_status":"pending","production_mutation":0}],
            "release_intelligence_v5":{"gate_status":"observe","risk_score":62,"confidence":.69,
                "blast_radius":["VM_Guard"],"selected_test_suites":["VM Guard"],"automatic_promotion":False},
            "autonomy":{"level":7,"effective_level":7,"level_name":"objective","effective_level_name":"objective"},
            "reliability":{"experiment_freeze_recommended":False},
        }

    def tearDown(self):self.tmp.cleanup()

    def test_v5_commands_registered(self):
        for cmd in ("plan","captrust","failurefamilies","forecast","shadowautomation","engineering","releaseintel"):
            self.assertIn(cmd,COMMANDS)

    def test_v5_read_only_commands_render(self):
        with patch("shared.vm_intelligence.admin_commands._snapshot",return_value=(self.snapshot,True)):
            self.assertIn("STRATEGIC PLAN",handle_intelligence_command("plan",[],self.root))
            self.assertIn("CAPABILITY TRUST",handle_intelligence_command("captrust",[],self.root))
            self.assertIn("FAILURE FAMILIES",handle_intelligence_command("failurefamilies",[],self.root))
            self.assertIn("PREDICTIVE OPERATIONS",handle_intelligence_command("forecast",[],self.root))
            self.assertIn("SHADOW AUTOMATION",handle_intelligence_command("shadowautomation",[],self.root))
            self.assertIn("ISOLATED ENGINEERING",handle_intelligence_command("engineering",[],self.root))
            self.assertIn("RELEASE INTELLIGENCE",handle_intelligence_command("releaseintel",[],self.root))

if __name__=="__main__":unittest.main()
