from __future__ import annotations

import unittest
from datetime import datetime, timezone

from shared.vm_core.intelligence_conflicts import detect_conflicts
from shared.vm_core.intelligence_contracts import EvidenceRef, IntelligenceKind, IntelligenceRecord
from shared.vm_core.intelligence_replay import compare_replay, intelligence_fingerprint


NOW = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def _record(*, polarity: str = "positive", subject_id: str = "123") -> IntelligenceRecord:
    evidence = EvidenceRef(
        source="VM_Relationship_Manager",
        observed_at_utc=NOW.isoformat(),
        confidence=0.9,
        source_trust=0.8,
        event_id=1,
    )
    return IntelligenceRecord.from_evidence(
        kind=IntelligenceKind.SIGNAL,
        record_type="relationship_trend",
        source="VM_Relationship_Manager",
        subject_type="contact",
        subject_id=subject_id,
        rationale="Relationship trend observed",
        evidence=[evidence],
        half_life_seconds=86400,
        now_utc=NOW,
        attributes={"polarity": polarity},
    )


class ReplayAndConflictTests(unittest.TestCase):
    def test_fingerprint_is_stable_for_identical_record(self):
        self.assertEqual(intelligence_fingerprint(_record()), intelligence_fingerprint(_record()))

    def test_duplicate_detection_is_exact(self):
        record = _record()
        result = detect_conflicts([record, record])
        self.assertEqual(len(result.duplicate_fingerprints), 1)
        self.assertEqual(result.contradictory_pairs, ())

    def test_explicit_opposite_polarity_is_contradiction(self):
        result = detect_conflicts([_record(polarity="positive"), _record(polarity="negative")])
        self.assertEqual(len(result.contradictory_pairs), 1)

    def test_different_subjects_do_not_conflict(self):
        result = detect_conflicts([
            _record(polarity="positive", subject_id="123"),
            _record(polarity="negative", subject_id="456"),
        ])
        self.assertEqual(result.contradictory_pairs, ())

    def test_replay_comparison_is_passive_and_set_based(self):
        base = [{"event_type": "intelligence.signal.a", "source": "x", "subject_type": "group", "subject_id": "1", "payload_json": "{}", "evidence_json": "{}"}]
        candidate = base + [{"event_type": "intelligence.signal.b", "source": "x", "subject_type": "group", "subject_id": "1", "payload_json": "{}", "evidence_json": "{}"}]
        result = compare_replay(base, candidate)
        self.assertEqual(result.baseline_count, 1)
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.unchanged_count, 1)
        self.assertEqual(len(result.added_fingerprints), 1)
        self.assertEqual(result.removed_fingerprints, ())


if __name__ == "__main__":
    unittest.main()
