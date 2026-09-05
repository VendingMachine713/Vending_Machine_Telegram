from __future__ import annotations

import unittest

from shared.vm_core.operator_home import operator_home


class OperatorHomeTests(unittest.TestCase):
    def test_healthy_snapshot_is_simple_and_read_only(self) -> None:
        snapshot = {
            "headline": {
                "registered_services": 5,
                "telemetry_running_services": 5,
                "fleet_heartbeat_expected_services": 5,
                "health_unhealthy": 0,
                "health_not_ready": 0,
                "open_incidents": 0,
                "telemetry_attention_running": 0,
                "fleet_heartbeat_incident_candidates": 0,
                "opportunities": 2,
                "canonical_opportunities": 1,
                "ranked_decisions": 1,
                "relationship_profiles": 12,
                "relationship_cooling": 0,
                "relationship_dormant": 0,
                "group_activity_profiles": 8,
                "risk_attention_subjects": 0,
                "posting_attention_destinations": 0,
                "canonical_reviews_awaiting_outcome": 0,
                "canonical_readiness": "READY",
                "canonical_evidence_health": "HEALTHY",
                "canonical_review_calibration": "CALIBRATED",
                "canonical_review_audit_status": "READY",
            },
            "automatic_acceptance": False,
            "automatic_execution": False,
            "external_action_authority": False,
        }

        text = operator_home(snapshot)

        self.assertIn("SYSTEM: HEALTHY", text)
        self.assertIn("Running services observed: 5/5", text)
        self.assertIn("Nothing currently requires operator attention", text)
        self.assertIn("Automatic execution: OFF", text)
        self.assertIn("External action authority: OFF", text)

    def test_attention_snapshot_surfaces_operator_relevant_counts(self) -> None:
        snapshot = {
            "headline": {
                "registered_services": 5,
                "telemetry_running_services": 4,
                "fleet_heartbeat_expected_services": 5,
                "health_unhealthy": 1,
                "health_not_ready": 1,
                "open_incidents": 2,
                "telemetry_attention_running": 1,
                "fleet_heartbeat_incident_candidates": 1,
                "risk_attention_subjects": 2,
                "posting_attention_destinations": 1,
                "canonical_reviews_awaiting_outcome": 3,
            },
            "automatic_acceptance": False,
            "automatic_execution": False,
            "external_action_authority": False,
        }

        text = operator_home(snapshot)

        self.assertIn("SYSTEM: ATTENTION", text)
        self.assertIn("1 unhealthy service(s)", text)
        self.assertIn("2 open incident(s)", text)
        self.assertIn("2 risk subject(s) need review", text)
        self.assertIn("3 completed review(s) await outcome evidence", text)


if __name__ == "__main__":
    unittest.main()
