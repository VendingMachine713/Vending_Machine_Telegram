from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.vm_intelligence.admin_commands import COMMANDS, handle_intelligence_command


class AdminCommandsV4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/"diagnostics").mkdir(parents=True)
        self.snapshot={
            "runtime_registry":[{"service":"VM_Guard","managed":True,"canonical_root":"bots/VM_Guard"}],
            "platform_registry":[{"service":"VM_Guard","managed":True,"owner":"VM_Guard","health_provider":"VM_Core","canonical_root":"bots/VM_Guard"}],
            "config_registry":[{"service":"VM_Guard","role":"configuration","secret_bearing":False,"exists":True,"path":"config.json"}],
            "platform_normalization":{"score":90,"violations":[]},
            "platform_drift":{"score":97,"counts":{"critical":0,"high":0,"medium":0,"low":1},"findings":[]},
            "reliability":{"compliance_pct":100,"breaches":0,"slos":[],"historical":{"max_burn_rate":0,"error_budgets_exhausted":0,"service_stats":[],"runbook_trust":[]}},
            "objectives":[{"status":"healthy","score":100,"title":"Keep healthy","plan":[]}],
            "autonomy":{"level":4,"level_name":"recover","requested_level":4,"effective_level":4,"effective_level_name":"recover","reason":"test","reliability_freeze":False,"freeze_until_utc":None},
            "runbooks":{"catalog":[{"key":"managed_service_offline","minimum_autonomy":4,"automatic":True}],"stats":{}},
            "dependency_graph":[{"source":"shared.vm_core.services","target":"VM_Guard"}],
            "release_gate":None,
            "attention_budget":{"useful":1,"noise":0,"noise_ratio":0.0,"automatic_decisions":2,"estimated_minutes_saved":6},
            "scorecard":{"overall":95},"incidents":[],"inbox":[],"security":{"score":100},"predictive_maintenance":[],
            "automation_opportunities":[],"goals":[],"meta_intelligence":{"self_health":"healthy"},"cto_priorities":[],
        }

    def tearDown(self):self.tmp.cleanup()

    def test_commands_are_registered(self):
        for cmd in ("registry","configreg","drift","slo","errorbudget","reliability","objective","autonomy","safe","whyact","runbooks","runbooktrust","impact","releasegate","attention"):
            self.assertIn(cmd,COMMANDS)

    def test_read_only_v4_commands(self):
        with patch("shared.vm_intelligence.admin_commands._snapshot",return_value=(self.snapshot,True)):
            self.assertIn("VM AUTHORITATIVE PLATFORM REGISTRY",handle_intelligence_command("registry",[],self.root))
            self.assertIn("VM CONFIG REGISTRY",handle_intelligence_command("configreg",[],self.root))
            self.assertIn("VM PLATFORM NORMALISATION",handle_intelligence_command("drift",[],self.root))
            self.assertIn("VM SLO STATUS",handle_intelligence_command("slo",[],self.root))
            self.assertIn("VM RELIABILITY ENGINEERING",handle_intelligence_command("reliability",[],self.root))
            self.assertIn("VM OBJECTIVES",handle_intelligence_command("objective",[],self.root))
            self.assertIn("VM RUNBOOKS",handle_intelligence_command("runbooks",[],self.root))
            self.assertIn("VM DEPENDENCY GRAPH",handle_intelligence_command("impact",[],self.root))
            self.assertIn("VM ATTENTION BUDGET",handle_intelligence_command("attention",[],self.root))

    def test_experiment_start_respects_reliability_freeze(self):
        frozen=dict(self.snapshot)
        frozen["reliability"]={"compliance_pct":80,"breaches":1,"slos":[],"experiment_freeze_recommended":True}
        with patch("shared.vm_intelligence.admin_commands._snapshot",return_value=(frozen,True)):
            text=handle_intelligence_command("experimentstart",["VM_Guard","latency","1","test"],self.root)
        self.assertIn("blocked",text.lower())


if __name__=="__main__":unittest.main()
