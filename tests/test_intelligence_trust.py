from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_contracts import EvidenceRef, IntelligenceContractError
from shared.vm_core.intelligence_trust import (
    DEFAULT_SOURCE_TRUST,
    canonical_entity_id,
    canonical_entity_parts,
    is_canonical_entity_id,
    source_trust,
    trust_foundation_summary,
    verify_evidence_provenance,
)


NOW = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc).isoformat()


class IntelligenceTrustTests(unittest.TestCase):
    def test_unknown_source_gets_conservative_default(self):
        self.assertEqual(source_trust("Unknown_Bot"), DEFAULT_SOURCE_TRUST)
        self.assertGreater(source_trust("VM_Guard"), DEFAULT_SOURCE_TRUST)
        self.assertEqual(source_trust("vm_core.learning"), source_trust("vm_core"))
        self.assertEqual(
            source_trust("vm_core.canonical_recommendations"),
            source_trust("vm_core"),
        )
        with self.assertRaises(IntelligenceContractError):
            source_trust("  ")

    def test_canonical_entity_id_is_stable_hides_raw_id_and_validates_shape(self):
        first = canonical_entity_id("contact", 123456)
        second = canonical_entity_id("contact", "123456")
        other = canonical_entity_id("group", 123456)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertNotIn("123456", first)
        self.assertTrue(first.startswith("telegram:contact:"))
        self.assertTrue(is_canonical_entity_id(first))
        self.assertEqual(canonical_entity_parts(first)[:2], ("telegram", "contact"))
        self.assertFalse(is_canonical_entity_id("123456"))
        self.assertFalse(is_canonical_entity_id("telegram:contact:123456"))
        self.assertFalse(is_canonical_entity_id("telegram:contact:not-a-valid-digest-value"))

    def test_provenance_verifies_matching_stored_event(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            subject = canonical_entity_id("chat", "abc")
            event_id = db.add_event(
                "intelligence.signal.activity",
                "Universal_Search",
                {"count": 3},
                subject_type="chat",
                subject_id=subject,
            )
            evidence = EvidenceRef(
                source="Universal_Search",
                observed_at_utc=NOW,
                event_id=event_id,
            )
            result = verify_evidence_provenance(evidence, root=root)
            self.assertTrue(result.valid)
            self.assertEqual(result.reason, "verified")
            self.assertEqual(result.stored_source, "Universal_Search")
            self.assertEqual(result.event_type, "intelligence.signal.activity")
            self.assertEqual(result.canonical_subject_id, subject)

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

    def test_provenance_missing_store_is_read_only_and_does_not_create_database(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = PlatformDB(root=root).path
            evidence = EvidenceRef(
                source="Universal_Search",
                observed_at_utc=NOW,
                event_id=1,
            )
            result = verify_evidence_provenance(evidence, root=root)
            self.assertFalse(result.valid)
            self.assertEqual(result.reason, "event_store_unavailable")
            self.assertFalse(path.exists())

    def test_provenance_missing_events_table_fails_closed_without_migration(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = PlatformDB(root=root).path
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as con:
                con.execute("CREATE TABLE untouched(value TEXT)")
            evidence = EvidenceRef(
                source="Universal_Search",
                observed_at_utc=NOW,
                event_id=1,
            )
            result = verify_evidence_provenance(evidence, root=root)
            self.assertFalse(result.valid)
            self.assertEqual(result.reason, "events_table_missing")
            with sqlite3.connect(path) as con:
                tables = {
                    row[0]
                    for row in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertEqual(tables, {"untouched"})

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

    def test_trust_foundation_summary_is_passive_and_reports_canonical_coverage(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            db.add_event(
                "intelligence.signal.one",
                "vm_core.relationship",
                {},
                subject_type="contact",
                subject_id=canonical_entity_id("contact", "1"),
            )
            db.add_event(
                "intelligence.signal.two",
                "legacy",
                {},
                subject_type="contact",
                subject_id="raw-contact-id",
            )
            db.add_event("intelligence.signal.three", "vm_core", {})
            summary = trust_foundation_summary(root=root)
            self.assertEqual(summary["event_store_status"], "OK")
            self.assertEqual(summary["intelligence_events_checked"], 3)
            self.assertEqual(summary["canonical_subject_events"], 1)
            self.assertEqual(summary["noncanonical_subject_events"], 1)
            self.assertEqual(summary["subjectless_events"], 1)
            self.assertEqual(summary["canonical_subject_coverage"], 0.5)
            self.assertTrue(summary["read_only"])
            self.assertFalse(summary["automatic_trust_change"])
            self.assertFalse(summary["automatic_rule_change"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])

    def test_trust_summary_missing_store_does_not_create_database(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = PlatformDB(root=root).path
            summary = trust_foundation_summary(root=root)
            self.assertEqual(summary["event_store_status"], "UNAVAILABLE")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
