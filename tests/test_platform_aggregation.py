from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.platform_aggregation import incident_intelligence_snapshot


class PlatformAggregationTests(unittest.TestCase):
    def test_snapshot_counts_and_correlates_attention_by_subject(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = PlatformDB(root=root)
            db.init()
            db.upsert_incident(
                "recovery:demo",
                "recovery",
                "vm_core",
                "ERROR",
                "Demo needs review",
                subject_type="service",
                subject_id="demo",
            )
            db.upsert_signal(
                "signal:demo",
                "runtime_risk",
                "Demo has elevated runtime risk",
                subject_type="service",
                subject_id="demo",
                score=90,
                confidence=0.8,
            )
            db.upsert_recommendation(
                "recommendation:demo",
                "operator_review",
                "Review demo",
                "Incident and signal agree",
                rule_id="test.rule",
                subject_type="service",
                subject_id="demo",
                priority=85,
                confidence=0.9,
            )

            snapshot = incident_intelligence_snapshot(root)

        self.assertEqual(snapshot["open_incident_count"], 1)
        self.assertEqual(snapshot["active_signal_count"], 1)
        self.assertEqual(snapshot["actionable_recommendation_count"], 1)
        self.assertEqual(snapshot["incident_severity_counts"]["ERROR"], 1)
        self.assertEqual(snapshot["correlated_subject_count"], 1)
        self.assertEqual(
            snapshot["correlated_subjects"],
            [{"subject_type": "service", "subject_id": "demo"}],
        )
        self.assertFalse(snapshot["automatic_execution"])
        self.assertFalse(snapshot["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
