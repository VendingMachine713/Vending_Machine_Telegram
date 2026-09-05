from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.group_member_audit import group_member_audit_summary
from shared.vm_core.intelligence_trust import canonical_entity_id


class GroupMemberAuditTests(unittest.TestCase):
    def _member(
        self,
        db: PlatformDB,
        *,
        group_native: str,
        user_native: str,
        classification: str,
        confidence: str,
        review_required: bool = False,
        canonical: bool = True,
        extra: dict | None = None,
    ) -> int:
        group = canonical_entity_id("chat", group_native)
        user = canonical_entity_id("user", user_native) if canonical else user_native
        attrs = {
            "group_subject_id": group,
            "classification": classification,
            "confidence_label": confidence,
            "reason_codes": ["TELEGRAM_BOT_FLAG"] if classification == "BOT_ACCOUNT" else ["NORMAL_USER_ACCOUNT"],
            "known_contact": classification == "KNOWN_CONTACT",
            "activity_state": "RECENT",
            "mutual_group_count": 2,
            "review_required": review_required,
            "username_present": True,
            "profile_photo_present": True,
            "audit_id": "audit-1",
        }
        attrs.update(extra or {})
        return db.add_event(
            "intelligence.observation.group_member_audit.member",
            "Universal_Search",
            {"confidence": 0.9, "attributes": attrs},
            subject_type="user",
            subject_id=user,
        )

    def _snapshot(self, db: PlatformDB, *, group_native: str, coverage: float = 95.0) -> int:
        group = canonical_entity_id("chat", group_native)
        return db.add_event(
            "intelligence.observation.group_member_audit.snapshot",
            "Universal_Search",
            {
                "confidence": 1.0,
                "attributes": {
                    "audit_id": "audit-1",
                    "visible_member_count": 4,
                    "expected_member_count": 4,
                    "coverage_percent": coverage,
                    "data_freshness": "FRESH",
                    "classification_counts": {
                        "LIKELY_HUMAN": 1,
                        "BOT_ACCOUNT": 1,
                        "UNCERTAIN": 1,
                        "KNOWN_CONTACT": 1,
                    },
                },
            },
            subject_type="chat",
            subject_id=group,
        )

    def test_builds_summary_cards_filters_member_rows_attention_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._member(db, group_native="g1", user_native="u1", classification="LIKELY_HUMAN", confidence="HIGH")
            self._member(db, group_native="g1", user_native="u2", classification="BOT_ACCOUNT", confidence="VERY_HIGH")
            self._member(
                db,
                group_native="g1",
                user_native="u3",
                classification="UNCERTAIN",
                confidence="LOW",
                review_required=True,
            )
            self._member(db, group_native="g1", user_native="u4", classification="KNOWN_CONTACT", confidence="HIGH")
            self._snapshot(db, group_native="g1")

            summary = group_member_audit_summary(root=root)
            self.assertEqual(summary["status"], "OK")
            self.assertEqual(summary["group_count"], 1)
            self.assertEqual(summary["audited_member_count"], 4)
            group = summary["groups"][0]
            self.assertEqual(group["summary_cards"]["members"], 4)
            self.assertEqual(group["summary_cards"]["likely_human"], 1)
            self.assertEqual(group["summary_cards"]["bot_accounts"], 1)
            self.assertEqual(group["summary_cards"]["uncertain"], 1)
            self.assertEqual(group["summary_cards"]["known_contacts"], 1)
            self.assertEqual(group["coverage_percent"], 95.0)
            self.assertEqual(len(group["audit_history"]), 1)
            self.assertEqual(group["review_required_count"], 1)
            codes = {item["code"] for item in group["attention"]}
            self.assertIn("HIGH_BOT_CONCENTRATION", codes)
            self.assertIn("HIGH_UNCERTAIN_SHARE", codes)
            self.assertIn("MEMBERS_REQUIRE_REVIEW", codes)
            self.assertIn("LIKELY_HUMAN", summary["filters"]["categories"])
            self.assertIn("HIGH", summary["filters"]["confidence_labels"])

    def test_latest_member_observation_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            old = self._member(db, group_native="g1", user_native="u1", classification="UNCERTAIN", confidence="LOW")
            new = self._member(db, group_native="g1", user_native="u1", classification="LIKELY_HUMAN", confidence="HIGH")
            summary = group_member_audit_summary(root=root)
            member = summary["groups"][0]["members"][0]
            self.assertEqual(member["classification"], "LIKELY_HUMAN")
            self.assertEqual(member["event_id"], new)
            self.assertNotEqual(member["event_id"], old)

    def test_noncanonical_user_is_ignored_and_raw_id_never_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._member(
                db,
                group_native="g1",
                user_native="raw-user-777",
                classification="LIKELY_HUMAN",
                confidence="HIGH",
                canonical=False,
            )
            self._member(db, group_native="g1", user_native="safe", classification="LIKELY_HUMAN", confidence="HIGH")
            summary = group_member_audit_summary(root=root)
            self.assertEqual(summary["noncanonical_events_ignored"], 1)
            self.assertEqual(summary["audited_member_count"], 1)
            self.assertNotIn("raw-user-777", repr(summary))

    def test_unknown_categories_fail_closed_to_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._member(db, group_native="g1", user_native="u1", classification="SURELY_HUMAN", confidence="MAGIC")
            summary = group_member_audit_summary(root=root)
            member = summary["groups"][0]["members"][0]
            self.assertEqual(member["classification"], "UNCERTAIN")
            self.assertEqual(member["confidence_label"], "INSUFFICIENT_EVIDENCE")

    def test_low_coverage_and_stale_snapshot_raise_attention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._member(db, group_native="g1", user_native="u1", classification="LIKELY_HUMAN", confidence="HIGH")
            group = canonical_entity_id("chat", "g1")
            db.add_event(
                "intelligence.observation.group_member_audit.snapshot",
                "Universal_Search",
                {"confidence": 1.0, "attributes": {
                    "audit_id": "audit-2",
                    "visible_member_count": 1,
                    "expected_member_count": 4,
                    "coverage_percent": 25,
                    "data_freshness": "STALE",
                    "classification_counts": {"LIKELY_HUMAN": 1},
                }},
                subject_type="chat",
                subject_id=group,
            )
            summary = group_member_audit_summary(root=root)
            codes = {item["code"] for item in summary["groups"][0]["attention"]}
            self.assertIn("LOW_AUDIT_COVERAGE", codes)
            self.assertIn("STALE_AUDIT", codes)

    def test_missing_database_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = PlatformDB(root=root).path
            summary = group_member_audit_summary(root=root)
            self.assertEqual(summary["status"], "UNAVAILABLE")
            self.assertFalse(path.exists())

    def test_no_bulk_message_or_external_action_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._member(db, group_native="g1", user_native="u1", classification="LIKELY_HUMAN", confidence="HIGH")
            before_events = db.events(limit=100)
            before_recommendations = db.recommendations(limit=100)
            summary = group_member_audit_summary(root=root)
            self.assertEqual(before_events, db.events(limit=100))
            self.assertEqual(before_recommendations, db.recommendations(limit=100))
            self.assertTrue(summary["read_only"])
            self.assertFalse(summary["bulk_message_action_available"])
            self.assertFalse(summary["automatic_outreach"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
