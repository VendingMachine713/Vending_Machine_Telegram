from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_contracts import (
    EvidenceRef,
    IntelligenceContractError,
    IntelligenceKind,
    IntelligenceRecord,
    evidence_confidence,
    freshness_score,
)
from shared.vm_core.publisher import BotEventPublisher


NOW = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def _evidence(*, hours_old: float = 0, confidence: float = 1.0,
              source_trust: float = 1.0, importance: float = 1.0,
              source: str = "VM_Relationship_Manager") -> EvidenceRef:
    observed = NOW - timedelta(hours=hours_old)
    return EvidenceRef(
        source=source,
        observed_at_utc=observed.isoformat(),
        confidence=confidence,
        source_trust=source_trust,
        importance=importance,
        event_id=17,
        reference="message:17",
    )


class IntelligenceContractTests(unittest.TestCase):
    def test_freshness_is_one_at_observation_and_half_after_one_half_life(self):
        self.assertAlmostEqual(freshness_score(NOW, half_life_seconds=3600, now_utc=NOW), 1.0)
        self.assertAlmostEqual(
            freshness_score(
                NOW - timedelta(hours=1),
                half_life_seconds=3600,
                now_utc=NOW,
            ),
            0.5,
        )

    def test_future_evidence_cannot_inflate_freshness(self):
        self.assertAlmostEqual(
            freshness_score(
                NOW + timedelta(minutes=5),
                half_life_seconds=3600,
                now_utc=NOW,
            ),
            1.0,
        )

    def test_evidence_confidence_is_explainable_weighted_mean(self):
        current = _evidence(confidence=0.8, source_trust=0.5, importance=3)
        stale = _evidence(hours_old=1, confidence=1.0, source_trust=1.0, importance=1)
        result = evidence_confidence(
            [current, stale],
            half_life_seconds=3600,
            now_utc=NOW,
        )
        self.assertAlmostEqual(result, 0.425)

    def test_contract_rejects_untraceable_or_invalid_evidence(self):
        with self.assertRaises(IntelligenceContractError):
            EvidenceRef(source="", observed_at_utc=NOW.isoformat())
        with self.assertRaises(IntelligenceContractError):
            EvidenceRef(source="bot", observed_at_utc="not-a-time")
        with self.assertRaises(IntelligenceContractError):
            IntelligenceRecord.from_evidence(
                kind=IntelligenceKind.SIGNAL,
                record_type="engagement_rise",
                source="VM_Relationship_Manager",
                subject_type="contact",
                subject_id="123",
                rationale="Observed activity increased",
                evidence=[],
                half_life_seconds=3600,
                now_utc=NOW,
            )

    def test_record_separates_kind_from_domain_type_and_calculates_confidence(self):
        record = IntelligenceRecord.from_evidence(
            kind=IntelligenceKind.INFERENCE,
            record_type="reengagement_opportunity",
            source="VM_Relationship_Manager",
            subject_type="contact",
            subject_id=123,
            rationale="Activity resumed after dormancy",
            evidence=[_evidence(confidence=0.9, source_trust=0.8)],
            half_life_seconds=86400,
            now_utc=NOW,
            attributes={"trend": "rising"},
        )
        self.assertEqual(record.event_type, "intelligence.inference.reengagement_opportunity")
        self.assertEqual(record.subject_id, "123")
        self.assertAlmostEqual(record.confidence, 0.72)
        self.assertAlmostEqual(record.freshness, 1.0)
        self.assertEqual(record.event_payload()["intelligence_schema_version"], 1)
        self.assertEqual(record.event_evidence()["items"][0]["event_id"], 17)

    def test_publisher_persists_canonical_intelligence_event(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = IntelligenceRecord.from_evidence(
                kind=IntelligenceKind.SIGNAL,
                record_type="relationship_activity_change",
                source="VM_Relationship_Manager",
                subject_type="contact",
                subject_id="123",
                rationale="Recent interaction rate exceeds baseline",
                evidence=[_evidence()],
                half_life_seconds=86400,
                now_utc=NOW,
            )
            publisher = BotEventPublisher("VM_Relationship_Manager", root, instance_id="test-instance")
            event_id = publisher.intelligence(record)

            self.assertIsNotNone(event_id)
            db = PlatformDB(root=root)
            rows = db.events(limit=1)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["event_type"], "intelligence.signal.relationship_activity_change")
            self.assertEqual(row["subject_type"], "contact")
            self.assertEqual(row["subject_id"], "123")
            self.assertEqual(row["correlation_id"], "brain:signal:contact:123")
            payload = json.loads(row["payload_json"])
            evidence = json.loads(row["evidence_json"])
            self.assertAlmostEqual(payload["confidence"], 1.0)
            self.assertAlmostEqual(payload["freshness"], 1.0)
            self.assertEqual(evidence["items"][0]["source"], "VM_Relationship_Manager")

    def test_publisher_fails_closed_on_source_mismatch(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = IntelligenceRecord.from_evidence(
                kind=IntelligenceKind.FACT,
                record_type="activity_observed",
                source="Universal_Search",
                subject_type="group",
                subject_id="99",
                rationale="Message activity observed",
                evidence=[_evidence(source="Universal_Search")],
                half_life_seconds=86400,
                now_utc=NOW,
            )
            publisher = BotEventPublisher("VM_Relationship_Manager", root)
            self.assertIsNone(publisher.intelligence(record))
            self.assertIn("source does not match", publisher.last_error or "")
            db = PlatformDB(root=root)
            db.init()
            self.assertEqual(db.events(limit=10), [])


if __name__ == "__main__":
    unittest.main()
