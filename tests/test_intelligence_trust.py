from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_contracts import EvidenceRef, IntelligenceContractError
from shared.vm_core.intelligence_trust import (
    DEFAULT_SOURCE_TRUST,
    canonical_entity_id,
    source_trust,
    verify_evidence_provenance,
)


NOW = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc).isoformat()


class IntelligenceTrustTests(unittest.TestCase):
    def test_unknown_source_gets_conservative_default(self):
        self.assertEqual(source_trust("Unknown_Bot"), DEFAULT_SOURCE_TRUST)
        self.assertGreater(source_trust("VM_Guard"), DEFAULT_SOURCE_TRUST)
        with self.assertRaises(IntelligenceContractError):
            source_trust("  ")

    def test_canonical_entity_id_is_stable_and_hides_raw_id(self):
        first = canonical_entity_id("contact", 123456)
        second = canonical_entity_id("contact", "123456")
        other = canonical_entity_id("group", 123456)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertNotIn("123456", first)
        self.assertTrue(first.startswith("telegram:contact:"))

    def test_provenance_verifies_matching_stored_event(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            event_id = db.add_event("signal.activity", "Universal_Search", {"count": 3})
            evidence = EvidenceRef(
                source="Universal_Search",
                observed_at_utc=NOW,
                event_id=event_id,
            )
            result = verify_evidence_provenance(evidence, root=root)
            self.assertTrue(result.valid)
            self.assertEqual(result.reason, "verified")
            self.assertEqual(result.stored_source, "Universal_Search")

    def test_provenance_fails_closed_for_missing_or_wrong_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            event_id = db.add_event("signal.activity", "Universal_Search", {})

            wrong = EvidenceRef(
                source="VM_Relationship_Manager",
                observed_at_utc=NOW,
                event_id=event_id,
            )
            wrong_result = verify_evidence_provenance(wrong, root=root)
            self.assertFalse(wrong_result.valid)
            self.assertEqual(wrong_result.reason, "source_mismatch")

            missing = EvidenceRef(
                source="Universal_Search",
                observed_at_utc=NOW,
                event_id=event_id + 999,
            )
            missing_result = verify_evidence_provenance(missing, root=root)
            self.assertFalse(missing_result.valid)
            self.assertEqual(missing_result.reason, "event_not_found")

    def test_external_reference_is_explicitly_unverified(self):
        with TemporaryDirectory() as tmp:
            evidence = EvidenceRef(
                source="Universal_Search",
                observed_at_utc=NOW,
                reference="external:source:abc",
            )
            result = verify_evidence_provenance(evidence, root=Path(tmp))
            self.assertFalse(result.valid)
            self.assertEqual(result.reason, "external_reference_unverified")


if __name__ == "__main__":
    unittest.main()
