from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_bridge import bridge_legacy_signals
from shared.vm_core.canonical_correlation import correlate_relationship_search
from shared.vm_core.canonical_shadow import ParityPolicy, evaluate_legacy_canonical_parity
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_audit import AuditQuery, query_intelligence_events
from shared.vm_core.intelligence_trust import canonical_entity_id


class CanonicalGuardShadowTests(unittest.TestCase):
    def _seed_dormant(self, db: PlatformDB, chat_id: str = "123", score: float = 72) -> None:
        db.upsert_signal(
            f"relationship:presence:999:{chat_id}",
            "relationship_dormant_presence",
            "Dormant relationship present",
            subject_type="chat",
            subject_id=chat_id,
            score=score,
            confidence=0.95,
            evidence={"lifecycle_stage": "dormant", "relationship_score": 28},
        )

    def _seed_cooling(self, db: PlatformDB, chat_id: str = "123") -> None:
        db.upsert_signal(
            f"relationship:presence:999:{chat_id}",
            "relationship_cooling_presence",
            "Cooling relationship present",
            subject_type="chat",
            subject_id=chat_id,
            score=65,
            confidence=0.90,
            evidence={"lifecycle_stage": "cooling", "relationship_score": 40},
        )

    def _seed_search(self, db: PlatformDB, chat_id: str = "123", score: float = 84) -> None:
        db.upsert_signal(
            f"search:activity_spike:{chat_id}",
            "search_activity_spike",
            "Activity above baseline",
            subject_type="chat",
            subject_id=chat_id,
            score=score,
            confidence=0.90,
            evidence={"ratio": 4.2, "window_hours": 24, "baseline_days": 7},
        )

    def _seed_guard(self, db: PlatformDB, chat_id: str = "123", score: float = 85) -> None:
        db.upsert_signal(
            f"guard:{chat_id}",
            "guard_risk_elevated",
            "Elevated risk",
            subject_type="chat",
            subject_id=chat_id,
            score=score,
            confidence=0.95,
            evidence={"reason_codes": ["test"], "message_id": 777},
        )

    def _seed_legacy_opportunity(
        self, db: PlatformDB, chat_id: str = "123", *, score: float, suppressed: bool
    ) -> None:
        db.upsert_signal(
            f"cross:relationship_activity:{chat_id}",
            "relationship_activity_opportunity",
            "Legacy opportunity",
            subject_type="chat",
            subject_id=chat_id,
            score=score,
            confidence=0.55 if suppressed else 0.90,
            evidence={"suppressed": suppressed, "guard_risk_score": 85 if suppressed else 0},
        )

    def test_guard_signal_is_bridged_without_message_level_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_guard(db)
            result = bridge_legacy_signals(root=root)
            self.assertEqual(result["published"], 1)
            rows = query_intelligence_events(
                AuditQuery(event_type_prefix="intelligence.signal.guard_risk_elevated", source="VM_Guard"),
                root=root,
            )
            self.assertEqual(len(rows), 1)
            evidence = json.loads(rows[0]["evidence_json"])
            attrs = evidence["items"][0]["attributes"]
            self.assertNotIn("message_id", attrs)
            self.assertNotIn("reason_codes", attrs)
            self.assertEqual(rows[0]["subject_id"], canonical_entity_id("chat", "123"))

    def test_recent_guard_suppresses_opportunity_to_legacy_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_dormant(db)
            self._seed_search(db)
            self._seed_guard(db)
            self.assertEqual(bridge_legacy_signals(root=root)["published"], 3)
            result = correlate_relationship_search(root=root)
            self.assertEqual(result["guard_suppressed"], 1)
            rows = query_intelligence_events(
                AuditQuery(event_type_prefix="intelligence.inference.relationship_reengagement_opportunity"),
                root=root,
            )
            payload = json.loads(rows[0]["payload_json"])
            attrs = payload["attributes"]
            self.assertTrue(attrs["suppressed"])
            self.assertTrue(attrs["guard_evidence_recent"])
            self.assertEqual(attrs["guard_risk_score"], 85.0)
            self.assertLessEqual(attrs["opportunity_score"], 40.0)
            self.assertFalse(attrs["recommendation_created"])
            self.assertFalse(attrs["automatic_execution"])

    def test_guard_in_different_chat_does_not_suppress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_dormant(db, "123")
            self._seed_search(db, "123")
            self._seed_guard(db, "456")
            bridge_legacy_signals(root=root)
            result = correlate_relationship_search(root=root)
            self.assertEqual(result["guard_suppressed"], 0)
            rows = query_intelligence_events(
                AuditQuery(event_type_prefix="intelligence.inference.relationship_reengagement_opportunity"),
                root=root,
            )
            attrs = json.loads(rows[0]["payload_json"])["attributes"]
            self.assertFalse(attrs["suppressed"])
            self.assertFalse(attrs["guard_evidence_recent"])

    def test_stale_guard_does_not_suppress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_dormant(db)
            self._seed_search(db)
            self._seed_guard(db)
            bridge_legacy_signals(root=root)
            stale = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
            with db.connect() as con:
                con.execute(
                    "UPDATE events SET created_at_utc=? WHERE event_type='intelligence.signal.guard_risk_elevated'",
                    (stale,),
                )
            result = correlate_relationship_search(root=root)
            self.assertEqual(result["guard_suppressed"], 0)
            rows = query_intelligence_events(
                AuditQuery(event_type_prefix="intelligence.inference.relationship_reengagement_opportunity"),
                root=root,
            )
            attrs = json.loads(rows[0]["payload_json"])["attributes"]
            self.assertFalse(attrs["guard_evidence_recent"])
            self.assertFalse(attrs["suppressed"])

    def test_cooling_is_bridged_but_not_promoted_during_parity_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_cooling(db)
            self._seed_search(db)
            bridge = bridge_legacy_signals(root=root)
            self.assertEqual(bridge["published"], 2)
            result = correlate_relationship_search(root=root)
            self.assertEqual(result["matched_subjects"], 0)
            self.assertEqual(result["published"], 0)

    def test_shadow_parity_passes_matching_suppressed_state_and_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_dormant(db, score=72)
            self._seed_search(db, score=84)
            self._seed_guard(db, score=85)
            self._seed_legacy_opportunity(db, score=40, suppressed=True)
            bridge_legacy_signals(root=root)
            correlate_relationship_search(root=root)
            parity = evaluate_legacy_canonical_parity(root=root)
            self.assertTrue(parity.passed)
            self.assertEqual(parity.status, "PASS")
            self.assertFalse(parity.automatic_execution)

    def test_shadow_parity_requires_review_on_suppression_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_dormant(db)
            self._seed_search(db)
            self._seed_legacy_opportunity(db, score=84, suppressed=True)
            bridge_legacy_signals(root=root)
            correlate_relationship_search(root=root)
            parity = evaluate_legacy_canonical_parity(
                root=root, policy=ParityPolicy(max_score_delta=100)
            )
            self.assertFalse(parity.passed)
            self.assertEqual(parity.status, "REVIEW_REQUIRED")
            self.assertEqual(len(parity.suppression_mismatches), 1)

    def test_shadow_parity_is_read_only_when_database_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parity = evaluate_legacy_canonical_parity(root=root)
            self.assertFalse(parity.passed)
            self.assertEqual(parity.status, "REVIEW_REQUIRED")
            self.assertFalse((root / "state").exists())


if __name__ == "__main__":
    unittest.main()
