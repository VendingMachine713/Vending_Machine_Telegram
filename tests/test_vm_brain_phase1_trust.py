from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shared.vm_core.confidence import (
    calibrated_confidence,
    evidence_quality,
    freshness_score,
    source_reliability_score,
)
from shared.vm_core.db import PlatformDB
from shared.vm_core.decision_engine import decision_summary, ranked_decisions
from shared.vm_core.learning import _ensure_schema as ensure_learning_schema
from shared.vm_core.rule_health import _rollout_bucket, health_summary, rule_health
from shared.vm_core.rule_registry import _ensure_schema as ensure_registry_schema


class VMBrainPhase1TrustTests(unittest.TestCase):
    def _db(self, root: Path) -> PlatformDB:
        db = PlatformDB(root=root)
        db.init()
        ensure_learning_schema(db)
        ensure_registry_schema(db)
        return db

    def _active_rule(
        self,
        db: PlatformDB,
        *,
        activated: str = "2026-01-02T00:00:00+00:00",
        rollout_percent: int = 100,
    ) -> None:
        with db.connect() as con:
            con.execute(
                """
                INSERT INTO intelligence_rule_versions(
                    rule_id,registry_version,source_rule_version,parent_registry_version,
                    score_delta,rollout_percent,status,created_by,created_at_utc,activated_at_utc,metadata_json
                ) VALUES('rule_a',1,1,NULL,5,?,'ACTIVE','test',?,?, '{}')
                """,
                (rollout_percent, activated, activated),
            )

    def _insert_outcome(
        self,
        db: PlatformDB,
        idx: int,
        value: float,
        created: str,
        *,
        outcome_type: str = "NEGATIVE",
        subject_id: str | None = None,
    ) -> None:
        subject = str(subject_id if subject_id is not None else idx)
        key = f"rec-{idx}"
        recommendation_id = db.upsert_recommendation(
            key,
            "review",
            "Review evidence",
            "test fixture",
            rule_id="rule_a",
            rule_version=1,
            subject_type="chat",
            subject_id=subject,
            priority=50,
            confidence=1,
        )
        with db.connect() as con:
            con.execute(
                """
                INSERT INTO intelligence_outcomes(
                    recommendation_id,recommendation_key,recommendation_type,rule_id,rule_version,
                    subject_type,subject_id,outcome_type,value_score,confidence,actor,note,evidence_json,created_at_utc
                ) VALUES(?,?,?,?,1,'chat',?,?,?,1,'test','', '{}',?)
                """,
                (recommendation_id, key, "review", "rule_a", subject, outcome_type, value, created),
            )

    def test_rule_health_requires_minimum_sample(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            self._active_rule(db)
            self._insert_outcome(db, 1, -50, "2026-01-03T00:00:00+00:00")
            row = rule_health(root)[0]
            self.assertEqual(row["status"], "INSUFFICIENT_DATA")
            self.assertFalse(row["rollback_recommended"])
            self.assertFalse(row["automatic_rollback"])

    def test_degraded_rule_recommends_but_never_auto_rolls_back(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            self._active_rule(db)
            for idx in range(1, 6):
                self._insert_outcome(db, idx, -40, f"2026-01-0{idx + 2}T00:00:00+00:00")
            row = rule_health(root)[0]
            self.assertEqual(row["status"], "DEGRADED")
            self.assertTrue(row["rollback_recommended"])
            summary = health_summary(root)
            self.assertFalse(summary["automatic_rollback"])
            self.assertFalse(summary["automatic_execution"])

    def test_partial_rollout_health_excludes_control_subjects(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            self._active_rule(db, rollout_percent=10)
            in_cohort = [str(i) for i in range(1, 500) if _rollout_bucket("rule_a", str(i)) < 10][:5]
            out_cohort = [str(i) for i in range(500, 1000) if _rollout_bucket("rule_a", str(i)) >= 10][:20]
            self.assertEqual(len(in_cohort), 5)
            self.assertEqual(len(out_cohort), 20)
            idx = 1
            for subject in in_cohort:
                self._insert_outcome(
                    db,
                    idx,
                    -40,
                    f"2026-01-{idx + 2:02d}T00:00:00+00:00",
                    subject_id=subject,
                )
                idx += 1
            for subject in out_cohort:
                self._insert_outcome(
                    db,
                    idx,
                    80,
                    "2026-01-20T00:00:00+00:00",
                    outcome_type="POSITIVE",
                    subject_id=subject,
                )
                idx += 1
            row = rule_health(root)[0]
            self.assertEqual(row["sample_size"], 5)
            self.assertEqual(row["post_activation_outcomes_in_cohort"], 5)
            self.assertEqual(row["post_activation_outcomes_excluded"], 20)
            self.assertEqual(row["status"], "DEGRADED")
            self.assertTrue(row["rollback_recommended"])

    def test_confidence_keeps_recommendation_and_verification_separate(self) -> None:
        evidence = {
            "source": "unit-test",
            "event_id": 1,
            "correlation_id": "c-1",
            "observed_at_utc": "2026-01-01T00:00:00+00:00",
            "subject_id": "123",
            "supporting_signals": ["s1", "s2"],
            "source_reliability": 0.8,
        }
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        metrics = calibrated_confidence(0.95, verification_confidence=0.40, evidence=evidence, now=now)
        self.assertEqual(metrics["recommendation_confidence"], 0.95)
        self.assertEqual(metrics["verification_confidence"], 0.40)
        self.assertTrue(metrics["verification_available"])
        self.assertEqual(evidence_quality(evidence), 1.0)
        self.assertEqual(freshness_score(evidence, now=now), 1.0)
        self.assertEqual(source_reliability_score(evidence), 0.8)
        self.assertLess(metrics["calibrated_confidence"], metrics["recommendation_confidence"])

    def test_missing_verification_never_copies_recommendation_confidence(self) -> None:
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        evidence = {
            "source": "unit-test",
            "event_id": 1,
            "correlation_id": "c-1",
            "observed_at_utc": "2026-01-01T00:00:00+00:00",
            "subject_id": "123",
            "supporting_signals": ["s1"],
        }
        metrics = calibrated_confidence(0.99, evidence=evidence, now=now)
        self.assertFalse(metrics["verification_available"])
        self.assertIsNone(metrics["verification_confidence"])
        self.assertLess(metrics["calibrated_confidence"], 0.99)

    def test_decision_engine_ranks_without_accepting_or_executing(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            db.upsert_recommendation(
                "rec:low",
                "review",
                "Review low priority",
                "low",
                rule_id="rule_low",
                subject_type="chat",
                subject_id="1",
                priority=30,
                confidence=0.7,
                evidence={"urgency_score": 20, "opportunity_score": 20, "risk_score": 20},
            )
            db.upsert_recommendation(
                "rec:high",
                "review",
                "Review high priority",
                "high",
                rule_id="rule_high",
                subject_type="chat",
                subject_id="2",
                priority=90,
                confidence=0.9,
                evidence={
                    "urgency_score": 95,
                    "opportunity_score": 90,
                    "estimated_value_score": 90,
                    "effort_score": 10,
                    "risk_score": 5,
                    "source": "test",
                    "event_id": 2,
                    "correlation_id": "c2",
                    "observed_at_utc": "2026-01-01T00:00:00+00:00",
                    "subject_id": "2",
                    "supporting_signals": ["s"],
                },
            )
            ranked = ranked_decisions(root)
            self.assertEqual(ranked[0]["recommendation_key"], "rec:high")
            self.assertFalse(ranked[0]["automatic_acceptance"])
            self.assertFalse(ranked[0]["automatic_execution"])
            with db.connect() as con:
                statuses = {
                    row["recommendation_key"]: row["status"]
                    for row in con.execute("SELECT recommendation_key,status FROM intelligence_recommendations")
                }
            self.assertEqual(statuses["rec:high"], "PROPOSED")
            self.assertEqual(statuses["rec:low"], "PROPOSED")

    def test_duplicate_suppression_and_conflicts_are_passive(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            for key, priority in (("rec:dup:a", 80), ("rec:dup:b", 60)):
                db.upsert_recommendation(
                    key,
                    "review",
                    "Review same subject",
                    "duplicate",
                    rule_id="rule_dup",
                    subject_type="chat",
                    subject_id="42",
                    priority=priority,
                    confidence=0.8,
                )
            db.upsert_recommendation(
                "rec:conflict",
                "guard_review",
                "Escalate same subject",
                "different action",
                rule_id="rule_guard",
                subject_type="chat",
                subject_id="42",
                priority=70,
                confidence=0.8,
            )
            ranked = ranked_decisions(root)
            duplicate_keys = [row["recommendation_key"] for row in ranked if row["recommendation_type"] == "review"]
            self.assertEqual(duplicate_keys, ["rec:dup:a"])
            duplicate = next(row for row in ranked if row["recommendation_key"] == "rec:dup:a")
            self.assertFalse(duplicate["risk_assessed"])
            self.assertEqual(duplicate["risk_score"], 50.0)
            summary = decision_summary(root)
            self.assertEqual(summary["conflict_count"], 1)
            self.assertTrue(summary["conflicts"][0]["requires_human_resolution"])
            self.assertFalse(summary["automatic_conflict_resolution"])

    def test_decision_summary_has_no_external_authority(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            self._db(root)
            summary = decision_summary(root)
            self.assertFalse(summary["automatic_acceptance"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
