from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_bridge import bridge_legacy_signals, canonical_record_from_legacy_signal
from shared.vm_core.canonical_correlation import correlate_relationship_search
from shared.vm_core.canonical_runtime import run_canonical_brain_pass
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id


class CanonicalRuntimeSecurityTests(unittest.TestCase):
    def test_supported_signal_with_non_chat_subject_fails_closed(self):
        row = {
            "signal_key": "relationship:presence:1:2",
            "signal_type": "relationship_dormant_presence",
            "subject_type": "contact",
            "subject_id": "2",
            "score": 80,
            "confidence": 0.9,
            "rationale": "test",
            "evidence_json": "{}",
            "updated_at_utc": "2026-09-05T00:00:00+00:00",
        }
        self.assertIsNone(canonical_record_from_legacy_signal(row))

    def test_spoofed_relationship_source_cannot_participate_in_correlation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            subject = canonical_entity_id("chat", "123")
            db.add_event(
                "intelligence.signal.relationship_dormant_presence",
                "Untrusted_Producer",
                {"confidence": 0.9, "attributes": {"lifecycle_stage": "dormant"}},
                subject_type="chat",
                subject_id=subject,
            )
            db.add_event(
                "intelligence.signal.search_activity_spike",
                "Universal_Search",
                {"confidence": 0.9, "attributes": {"ratio": 4.0}},
                subject_type="chat",
                subject_id=subject,
            )
            result = correlate_relationship_search(root=root)
            self.assertEqual(result["matched_subjects"], 0)
            self.assertEqual(result["published"], 0)

    def test_canonical_pass_remains_inference_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            db.upsert_signal(
                "relationship:presence:999:123",
                "relationship_dormant_presence",
                "Dormant relationship present",
                subject_type="chat",
                subject_id="123",
                score=75,
                confidence=0.95,
                evidence={
                    "contact_id": "999",
                    "lifecycle_stage": "dormant",
                    "relationship_score": 25,
                },
            )
            db.upsert_signal(
                "search:activity_spike:123",
                "search_activity_spike",
                "Activity above baseline",
                subject_type="chat",
                subject_id="123",
                score=85,
                confidence=0.90,
                evidence={"ratio": 4.2, "window_hours": 24, "baseline_days": 7},
            )
            result = run_canonical_brain_pass(root=root)
            self.assertEqual(result["bridge"]["published"], 2)
            self.assertEqual(result["correlation"]["published"], 1)
            self.assertEqual(result["recommendations_created"], 0)
            self.assertFalse(result["automatic_execution"])
            self.assertEqual(db.recommendations(20), [])

            events = db.events(20)
            inference = next(
                row for row in events
                if row["event_type"] == "intelligence.inference.relationship_reengagement_opportunity"
            )
            payload = json.loads(inference["payload_json"])
            self.assertFalse(payload["attributes"]["recommendation_created"])
            self.assertFalse(payload["attributes"]["automatic_execution"])


if __name__ == "__main__":
    unittest.main()
