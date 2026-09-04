from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_health import canonical_evidence_health
from shared.vm_core.canonical_readiness import canonical_operator_summary
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id
from shared.vm_core.mission_control import mission_control


class CanonicalEvidenceHealthTests(unittest.TestCase):
    def _seed(self, db: PlatformDB, chat_id: str, *, suppressed: bool = False) -> None:
        db.add_event(
            "intelligence.inference.relationship_reengagement_opportunity",
            "vm_core",
            {
                "confidence": 0.8,
                "attributes": {
                    "opportunity_score": 70,
                    "suppressed": suppressed,
                    "automatic_execution": False,
                    "recommendation_created": False,
                },
            },
            subject_type="chat",
            subject_id=canonical_entity_id("chat", chat_id),
        )

    def test_missing_database_is_read_only_no_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            health = canonical_evidence_health(root=root)
            self.assertEqual(health.status, "NO_EVIDENCE")
            self.assertTrue(health.stale)
            self.assertEqual(health.total_inference_events, 0)
            self.assertEqual(health.distinct_subjects, 0)
            self.assertFalse((root / "state").exists())
            self.assertFalse(health.automatic_execution)

    def test_recent_evidence_reports_active_shadow_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed(db, "100")
            self._seed(db, "101", suppressed=True)
            now = datetime.now(timezone.utc) + timedelta(minutes=1)
            health = canonical_evidence_health(root=root, now=now)
            self.assertEqual(health.status, "ACTIVE_SHADOW")
            self.assertFalse(health.stale)
            self.assertEqual(health.total_inference_events, 2)
            self.assertEqual(health.distinct_subjects, 2)
            self.assertEqual(health.events_last_24h, 2)
            self.assertEqual(health.events_last_7d, 2)
            self.assertEqual(health.events_last_30d, 2)
            self.assertEqual(health.latest_suppressed_subjects, 1)
            self.assertAlmostEqual(health.latest_suppressed_ratio, 0.5)

    def test_old_relative_to_evaluation_time_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed(db, "200")
            now = datetime.now(timezone.utc) + timedelta(days=5)
            health = canonical_evidence_health(root=root, now=now, stale_after_hours=72)
            self.assertEqual(health.status, "STALE")
            self.assertTrue(health.stale)
            self.assertGreater(health.newest_age_hours or 0.0, 72.0)
            self.assertEqual(health.events_last_24h, 0)

    def test_operator_surfaces_health_without_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed(db, "300")
            canonical = canonical_operator_summary(root=root)
            self.assertIn("evidence_health", canonical)
            self.assertFalse(canonical["automatic_execution"])
            summary = mission_control(root)
            self.assertEqual(
                summary["headline"]["canonical_evidence_health"],
                summary["canonical"]["evidence_health"]["status"],
            )
            self.assertEqual(
                summary["attention"]["canonical_evidence_stale"],
                summary["canonical"]["evidence_health"]["stale"],
            )
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
