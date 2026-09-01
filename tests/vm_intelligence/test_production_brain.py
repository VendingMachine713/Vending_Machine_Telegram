import tempfile, unittest
from pathlib import Path
from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.events import Event
from shared.vm_intelligence.brain import Brain
from shared.vm_intelligence.policy import PolicyEngine

class ProductionBrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name); (self.root/"bots"/"A").mkdir(parents=True)
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
    def tearDown(self): self.tmp.cleanup()

    def test_brain_snapshot(self):
        for _ in range(20):
            self.store.add_event(Event(source="A",kind="health",action="check",outcome="success",duration_ms=50))
        s=Brain(self.store,self.root).executive_snapshot()
        self.assertEqual(s["inventory"]["bot_count"],1)
        self.assertGreater(s["scorecard"]["overall"],80)

    def test_policy_blocks_dangerous(self):
        p=PolicyEngine()
        self.assertEqual(p.decide("delete_master_data",reversible=False,risk="high",confidence=1).authority,"blocked")
        self.assertEqual(p.decide("run_tests",reversible=True,risk="low",confidence=.99).authority,"automatic")

    def test_learning(self):
        eid=self.store.create_experiment(name="x",source="A",hypothesis="h",metric="rate",baseline=.5)
        self.store.finish_experiment(eid,result="win",candidate=.7)
        lessons=Brain(self.store,self.root).learning.lessons()
        self.assertEqual(lessons[0]["delta"],.2)

if __name__=="__main__": unittest.main()
