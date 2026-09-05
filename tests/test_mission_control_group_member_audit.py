from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.group_member_audit_view import render_group_member_audit
from shared.vm_core.intelligence_trust import canonical_entity_id
from shared.vm_core.mission_control import mission_control


class MissionControlGroupMemberAuditTests(unittest.TestCase):
    def test_mission_control_exposes_read_only_group_member_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            group = canonical_entity_id("chat", "group-1")
            user = canonical_entity_id("user", "user-1")
            db.add_event(
                "intelligence.observation.group_member_audit.member",
                "Universal_Search",
                {
                    "confidence": 0.9,
                    "attributes": {
                        "group_subject_id": group,
                        "classification": "UNCERTAIN",
                        "confidence_label": "LOW",
                        "reason_codes": ["INSUFFICIENT_SIGNAL"],
                        "known_contact": False,
                        "activity_state": "UNKNOWN",
                        "mutual_group_count": 1,
                        "review_required": True,
                        "audit_id": "audit-1",
                    },
                },
                subject_type="user",
                subject_id=user,
            )
            db.add_event(
                "intelligence.observation.group_member_audit.snapshot",
                "Universal_Search",
                {
                    "confidence": 1.0,
                    "attributes": {
                        "audit_id": "audit-1",
                        "visible_member_count": 1,
                        "expected_member_count": 1,
                        "coverage_percent": 100,
                        "data_freshness": "FRESH",
                        "classification_counts": {"UNCERTAIN": 1},
                    },
                },
                subject_type="chat",
                subject_id=group,
            )

            summary = mission_control(root)
            audit = summary["group_member_audit"]

            self.assertEqual(audit["group_count"], 1)
            self.assertEqual(summary["headline"]["group_member_audited_members"], 1)
            self.assertEqual(summary["headline"]["group_member_audit_attention_groups"], 1)
            self.assertEqual(len(summary["attention"]["group_member_audit_groups"]), 1)
            self.assertTrue(audit["read_only"])
            self.assertFalse(audit["bulk_message_action_available"])
            self.assertFalse(audit["automatic_outreach"])
            self.assertFalse(audit["automatic_execution"])
            self.assertFalse(audit["external_action_authority"])

    def test_renderer_contains_requested_screen_sections(self) -> None:
        summary = {
            "status": "OK",
            "group_count": 1,
            "audited_member_count": 1,
            "attention_group_count": 1,
            "filters": {
                "categories": ["LIKELY_HUMAN", "UNCERTAIN"],
                "confidence_labels": ["HIGH", "LOW"],
            },
            "groups": [{
                "group_subject_id": "telegram:chat:1234567890abcdef12345678",
                "latest_audit_utc": "2026-09-06T01:00:00+00:00",
                "coverage_percent": 100,
                "data_freshness": "FRESH",
                "summary_cards": {
                    "members": 1,
                    "likely_human": 0,
                    "bot_accounts": 0,
                    "deleted": 0,
                    "uncertain": 1,
                    "known_contacts": 0,
                    "restricted": 0,
                },
                "attention": [{"severity": "MEDIUM", "code": "MEMBERS_REQUIRE_REVIEW", "count": 1}],
                "members": [{
                    "member_subject_id": "telegram:user:abcdef1234567890abcdef12",
                    "classification": "UNCERTAIN",
                    "confidence_label": "LOW",
                    "reason_codes": ["INSUFFICIENT_SIGNAL"],
                    "activity_state": "UNKNOWN",
                    "mutual_group_count": 1,
                    "known_contact": False,
                    "review_required": True,
                    "evidence_created_at_utc": "2026-09-06T01:00:00+00:00",
                }],
                "audit_history": [{
                    "created_at_utc": "2026-09-06T01:00:00+00:00",
                    "visible_member_count": 1,
                    "coverage_percent": 100,
                    "classification_counts": {"UNCERTAIN": 1},
                }],
            }],
            "read_only": True,
            "automatic_outreach": False,
            "automatic_execution": False,
            "external_action_authority": False,
        }

        text = render_group_member_audit(summary)

        for heading in (
            "SUMMARY CARDS",
            "ATTENTION REQUIRED",
            "FILTERS",
            "MEMBER TABLE",
            "DETAIL PANEL",
            "AUDIT HISTORY",
            "OPERATOR ACTIONS",
            "SAFETY",
        ):
            self.assertIn(heading, text)
        self.assertIn("Bulk messaging is NOT available", text)
        self.assertIn("Automatic outreach: OFF", text)


if __name__ == "__main__":
    unittest.main()
