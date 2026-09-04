from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id
from shared.vm_core.opportunity_intelligence import canonical_opportunities, opportunity_summary


class CanonicalOpportunityEngineTests(unittest.TestCase):
    def _relationship_event(
        self,
        db: PlatformDB,
        native_subject: str,
        signal: str,
        *,
        attributes: dict | None = None,
        confidence: float = 0.8,
    ) -> int:
        return db.add_event(
            f"intelligence.signal.{signal}",
            "VM_Relationship_Manager",
            {"confidence": confidence, "attributes": dict(attributes or {})},
            subject_type="chat",
            subject_id=canonical_entity_id("chat", native_subject),
        )

    def _search_event(
        self,
        db: PlatformDB,
        native_subject: str,
        *,
        ratio: float = 4.0,
        messages: int = 50,
        confidence: float = 0.9,
    ) -> int:
        return db.add_event(
            "intelligence.signal.search_activity_spike",
            "Universal_Search",
            {
                "confidence": confidence,
                "attributes": {
                    "recent_24h_messages": messages,
                    "baseline_daily_messages": 10,
                    "recent_24h_ads": 4,
                    "ratio": ratio,
                    "window_hours": 24,
                    "baseline_days": 7,
                },
            },
            subject_type="chat",
            subject_id=canonical_entity_id("chat", native_subject),
        )

    def test_cross_domain_relationship_and_group_evidence_rank_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            rel_event = self._relationship_event(
                db,
                "12345",
                "relationship_dormant_presence",
                attributes={
                    "relationship_type": "client",
                    "relationship_score": 25,
                    "trust_score": 70,
                    "days_overdue": 30,
                },
                confidence=0.8,
            )
            search_event = self._search_event(db, "12345", ratio=5.0, messages=60)

            rows = canonical_opportunities(root)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["opportunity_type"], "REENGAGEMENT_ACTIVITY_REVIEW")
            self.assertTrue(row["cross_domain_evidence"])
            self.assertGreater(row["opportunity_score"], 0)
            self.assertEqual(row["confidence"], 0.85)
            self.assertEqual(row["evidence_event_ids"], sorted([rel_event, search_event]))
            self.assertNotIn("12345", row["canonical_subject_id"])
            self.assertTrue(row["diagnostic_candidate_only"])

    def test_business_reload_stays_visible_without_group_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._relationship_event(
                db,
                "7",
                "business_reload_opportunity",
                attributes={"transaction_count": 5, "days_since_last_business": 14},
                confidence=0.95,
            )
            rows = canonical_opportunities(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["opportunity_type"], "BUSINESS_RELOAD_REVIEW")
            self.assertFalse(rows[0]["cross_domain_evidence"])
            self.assertTrue(rows[0]["business_reload_signal"])

    def test_dormant_client_branch_has_explicit_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._relationship_event(
                db,
                "8",
                "business_dormant_client_opportunity",
                attributes={"days_inactive": 90},
            )
            row = canonical_opportunities(root)[0]
            self.assertEqual(row["opportunity_type"], "DORMANT_CLIENT_REVIEW")
            self.assertTrue(row["dormant_client_signal"])

    def test_higher_cross_domain_evidence_ranks_above_weaker_relationship_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._relationship_event(
                db,
                "strong",
                "relationship_dormant_presence",
                attributes={"relationship_score": 20, "days_overdue": 30},
            )
            self._search_event(db, "strong", ratio=5.0, messages=70)
            self._relationship_event(
                db,
                "weak",
                "relationship_cooling_presence",
                attributes={"relationship_score": 48, "days_overdue": 3},
            )
            rows = canonical_opportunities(root)
            self.assertEqual(len(rows), 2)
            self.assertGreater(rows[0]["opportunity_score"], rows[1]["opportunity_score"])
            self.assertTrue(rows[0]["cross_domain_evidence"])

    def test_group_only_signal_does_not_become_relationship_opportunity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._search_event(db, "group-only")
            self.assertEqual(canonical_opportunities(root), [])

    def test_canonical_opportunity_synthesis_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._relationship_event(db, "safe", "relationship_dormant_presence")
            self._search_event(db, "safe")
            before_events = db.events(limit=100)
            before_recommendations = db.recommendations(limit=100)
            rows = canonical_opportunities(root)
            self.assertEqual(before_events, db.events(limit=100))
            self.assertEqual(before_recommendations, db.recommendations(limit=100))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertFalse(row["risk_fusion_applied"])
            self.assertFalse(row["recommendation_created"])
            self.assertFalse(row["automatic_acceptance"])
            self.assertFalse(row["automatic_execution"])
            self.assertFalse(row["automatic_threshold_change"])
            self.assertFalse(row["automatic_rule_change"])
            self.assertFalse(row["external_action_authority"])

    def test_summary_preserves_legacy_contract_and_adds_canonical_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            db.upsert_signal(
                "legacy:1",
                "relationship_momentum",
                "legacy",
                subject_type="contact",
                subject_id="1",
                score=80,
                confidence=0.8,
            )
            self._relationship_event(db, "canonical", "relationship_dormant_presence")
            self._search_event(db, "canonical")
            summary = opportunity_summary(root)
            self.assertEqual(summary["count"], 1)
            self.assertEqual(len(summary["top_opportunities"]), 1)
            self.assertEqual(summary["canonical_count"], 1)
            self.assertEqual(len(summary["canonical_top_opportunities"]), 1)
            self.assertEqual(summary["canonical_cross_domain_count"], 1)
            self.assertFalse(summary["canonical_risk_fusion_applied"])
            self.assertTrue(summary["read_only_canonical_synthesis"])
            self.assertFalse(summary["automatic_execution"])

    def test_missing_database_returns_empty_canonical_candidates_without_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = PlatformDB(root=root).path
            self.assertEqual(canonical_opportunities(root), [])
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
