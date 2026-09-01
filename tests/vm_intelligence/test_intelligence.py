import tempfile
import unittest
from pathlib import Path

from shared.vm_intelligence.events import Event, Telemetry
from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.analytics import IntelligenceAnalyzer
from shared.vm_intelligence.recommendations import RecommendationEngine
from shared.vm_intelligence.reporting import build_report


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = IntelligenceStore(Path(self.tmp.name) / "intel.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_event_validation(self):
        with self.assertRaises(ValueError):
            Event(source="", kind="health", action="check")

    def test_telemetry_and_summary(self):
        t = Telemetry(self.store, "VM_Guard")
        self.assertTrue(t.emit("health", "poll", outcome="success", duration_ms=10))
        self.assertTrue(t.emit("health", "poll", outcome="failure", duration_ms=20))
        summary = IntelligenceAnalyzer(self.store).summary(24)
        self.assertEqual(summary["events"], 2)
        self.assertEqual(summary["failures"], 1)
        self.assertEqual(summary["failure_rate"], 0.5)

    def test_high_failure_anomaly_and_recommendation(self):
        for _ in range(5):
            self.store.add_event(Event(source="Bot", kind="task", action="send", outcome="failure"))
        analyzer = IntelligenceAnalyzer(self.store)
        anomalies = analyzer.anomalies(24)
        self.assertTrue(any(a["type"] == "high_failure_rate" for a in anomalies))
        engine = RecommendationEngine(self.store, analyzer)
        engine.refresh(24)
        recs = self.store.open_recommendations()
        self.assertEqual(len(recs), 1)
        engine.refresh(24)
        self.assertEqual(len(self.store.open_recommendations()), 1)

    def test_experiment_registry(self):
        eid = self.store.create_experiment(
            name="schedule-A", source="Smart_Auto_Poster_V2",
            hypothesis="new schedule improves success rate", metric="success_rate",
            baseline=0.80
        )
        self.store.finish_experiment(eid, result="win", candidate=0.91)
        with self.store.connect() as con:
            row = con.execute("SELECT * FROM experiments WHERE experiment_id=?", (eid,)).fetchone()
        self.assertEqual(row["result"], "win")
        self.assertEqual(row["candidate"], 0.91)

    def test_report(self):
        self.store.add_event(Event(source="A", kind="health", action="check", outcome="success"))
        analyzer = IntelligenceAnalyzer(self.store)
        engine = RecommendationEngine(self.store, analyzer)
        report = build_report(self.store, analyzer, engine, hours=24)
        self.assertEqual(report["summary"]["events"], 1)
        self.assertIn("recommendations", report)


if __name__ == "__main__":
    unittest.main()
