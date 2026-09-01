import json,tempfile,unittest
from pathlib import Path
from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.ingest import ingest_vm_diagnostics
from shared.vm_intelligence.agent import IntelligenceAgent
from shared.vm_intelligence.policy import PolicyEngine
from shared.vm_intelligence.techdebt import TechnicalDebtScanner

class V2Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
        (self.root/"bots"/"A").mkdir(parents=True);(self.root/"shared").mkdir();(self.root/"diagnostics").mkdir()
        (self.root/"bots"/"A"/"main.py").write_text("print('ok')\n",encoding="utf-8")
    def tearDown(self):self.t.cleanup()

    def test_diagnostic_ingest_is_idempotent(self):
        f=self.root/"diagnostics"/"health_report.json"
        f.write_text(json.dumps([{"service":"A","status":"READY"}]),encoding="utf-8")
        s=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
        self.assertEqual(ingest_vm_diagnostics(s,self.root),1)
        self.assertEqual(ingest_vm_diagnostics(s,self.root),0)

    def test_agent_cycle_generates_attention_and_brief(self):
        (self.root/"diagnostics"/"health_report.json").write_text(json.dumps([{"service":"A","status":"READY"}]),encoding="utf-8")
        result=IntelligenceAgent(self.root).cycle()
        self.assertIn("score",result)
        self.assertTrue((self.root/"diagnostics"/"intelligence_attention.json").exists())
        self.assertTrue((self.root/"diagnostics"/"intelligence_brief.txt").exists())

    def test_technical_debt_scan(self):
        r=TechnicalDebtScanner(self.root).scan()
        self.assertEqual(r["python_files"],1)
        self.assertIn("debt_score",r)

    def test_schema_v2_tables(self):
        s=IntelligenceStore(self.root/"state"/"x.db")
        with s.connect() as c:
            names={x["name"] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in {"incidents","decisions","improvements","snapshots","release_baselines"}:
            self.assertIn(name,names)

if __name__=="__main__":unittest.main()
