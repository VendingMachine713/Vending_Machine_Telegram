from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_audit import AuditQuery, audit_summary, query_intelligence_events
from shared.vm_core.intelligence_shadow import ShadowPolicy, evaluate_shadow


class IntelligenceAuditShadowTests(unittest.TestCase):
    def _root(self) -> tempfile.TemporaryDirectory:
        return tempfile.TemporaryDirectory()

    def test_audit_missing_database_is_read_only(self):
        with self._root() as directory:
            root = Path(directory)
            self.assertEqual(query_intelligence_events(root=root), [])
            self.assertFalse((root / "state").exists())

    def test_audit_filters_canonical_events(self):
        with self._root() as directory:
            root = Path(directory)
            db = PlatformDB(root=root)
            db.init()
            db.add_event(
                "intelligence.signal.relationship_trend",
                "VM_Relationship_Manager",
                {"confidence": 0.8},
                subject_type="contact",
                subject_id="abc",
                correlation_id="brain:signal:contact:abc",
            )
            db.add_event("service.started", "VM_Relationship_Manager", {})
            rows = query_intelligence_events(
                AuditQuery(source="VM_Relationship_Manager", subject_type="contact", subject_id="abc"),
                root=root,
            )
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["event_type"].startswith("intelligence."))

    def test_audit_summary_is_passive_and_tolerates_bad_payload(self):
        with self._root() as directory:
            root = Path(directory)
            db = PlatformDB(root=root)
            db.init()
            db.add_event(
                "intelligence.fact.activity_observed",
                "Universal_Search",
                {"confidence": 0.75},
                subject_type="group",
                subject_id="g1",
            )
            path = db.path
            con = sqlite3.connect(path)
            try:
                con.execute(
                    "INSERT INTO events(event_type,source,payload_json,created_at_utc,event_version,severity,evidence_json) VALUES(?,?,?,?,?,?,?)",
                    ("intelligence.signal.bad", "test", "{bad", "2026-09-05T00:00:00+00:00", 2, "INFO", "{}"),
                )
                con.commit()
            finally:
                con.close()
            summary = audit_summary(root=root)
            self.assertEqual(summary["event_count"], 2)
            self.assertTrue(summary["read_only"])
            self.assertFalse(summary["automatic_execution"])
            self.assertAlmostEqual(summary["mean_confidence"], 0.75)

    @staticmethod
    def _event(name: str) -> dict[str, str]:
        return {
            "event_type": f"intelligence.signal.{name}",
            "source": "test",
            "subject_type": "group",
            "subject_id": "1",
            "payload_json": json.dumps({"name": name}),
            "evidence_json": "{}",
        }

    def test_shadow_passes_small_bounded_delta(self):
        baseline = [self._event("a"), self._event("b"), self._event("c"), self._event("d")]
        candidate = baseline + [self._event("e")]
        result = evaluate_shadow(
            baseline,
            candidate,
            policy=ShadowPolicy(max_added=2, max_removed=1, max_change_ratio=0.30),
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.status, "PASS")
        self.assertFalse(result.automatic_execution)

    def test_shadow_requires_review_for_large_behavior_delta(self):
        baseline = [self._event("a"), self._event("b"), self._event("c"), self._event("d")]
        candidate = [self._event("x"), self._event("y")]
        result = evaluate_shadow(
            baseline,
            candidate,
            policy=ShadowPolicy(max_added=1, max_removed=1, max_change_ratio=0.25),
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.status, "REVIEW_REQUIRED")
        self.assertIn("change_ratio_exceeded", result.reasons)

    def test_shadow_fails_closed_without_required_baseline(self):
        result = evaluate_shadow([], [self._event("new")])
        self.assertFalse(result.passed)
        self.assertIn("baseline_required", result.reasons)


if __name__ == "__main__":
    unittest.main()
