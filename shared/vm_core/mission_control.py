from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical_readiness import canonical_operator_summary
from .canonical_recommendation_lifecycle import canonical_review_lifecycle_summary
from .canonical_recommendations import canonical_recommendation_summary
from .canonical_review_audit import canonical_review_audit_summary
from .canonical_review_calibration import canonical_review_calibration_summary
from .canonical_review_feedback import canonical_review_feedback_summary
from .db import PlatformDB
from .decision_engine import decision_summary
from .entity_graph import entity_graph
from .fleet_heartbeat import fleet_heartbeat_snapshot
from .group_search_intelligence import group_search_intelligence_summary
from .health_contract import health_snapshot
from .intelligence_trust import trust_foundation_summary
from .opportunity_intelligence import opportunity_summary
from .paths import project_root
from .platform_aggregation import incident_intelligence_snapshot
from .platform_registry import service_registry
from .posting_intelligence import posting_intelligence_summary
from .relationship_intelligence import relationship_intelligence_summary
from .risk_fusion import canonical_risk_fusion_summary, risk_adjusted_canonical_opportunities
from .rule_health import health_summary
from .service_adapters import adapter_registry

MISSION_CONTROL_CONTRACT_VERSION = 4
MISSION_CONTROL_PLATFORM_REVISION = 3


def mission_control(root: Path | None = None, *, limit: int = 20) -> dict[str, Any]:
    """Return one passive, operator-oriented snapshot of VM Brain and platform state."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    services = db.services()
    incidents = db.incidents(limit=limit, status="OPEN")
    signals = db.signals(limit=limit, status="ACTIVE")
    decisions = decision_summary(root, limit=limit)
    opportunities = opportunity_summary(root, limit=limit)
    risk_fusion = canonical_risk_fusion_summary(root=root, limit=max(100, limit * 20))
    risk_adjusted_opportunities = risk_adjusted_canonical_opportunities(root=root, limit=limit)
    graph = entity_graph(root, limit=max(100, limit * 10))
    trust_foundation = trust_foundation_summary(root=root, limit=max(100, limit * 10))
    relationship_intelligence = relationship_intelligence_summary(
        root=root,
        limit=max(100, limit * 20),
        profile_limit=limit,
    )
    group_search_intelligence = group_search_intelligence_summary(
        root=root,
        limit=max(100, limit * 20),
        group_limit=limit,
    )
    posting_intelligence = posting_intelligence_summary(root=root, limit=limit)
    canonical = canonical_operator_summary(root=root)
    canonical_recommendations = canonical_recommendation_summary(root=root, limit=limit)
    canonical_lifecycle = canonical_review_lifecycle_summary(root=root, limit=max(100, limit * 10))
    canonical_feedback = canonical_review_feedback_summary(root=root, limit=max(100, limit * 10))
    canonical_review_calibration = canonical_review_calibration_summary(root=root)
    canonical_review_audit = canonical_review_audit_summary(root=root, limit=limit)
    readiness = canonical["canonical_readiness"]
    evidence_health = canonical["evidence_health"]
    calibration = canonical["calibration"]

    registry = service_registry(root)
    adapters = adapter_registry(root)
    fleet_heartbeat = fleet_heartbeat_snapshot(root)
    telemetry = fleet_heartbeat["telemetry"]
    platform_health = health_snapshot(db.health_records())
    platform_intelligence = incident_intelligence_snapshot(root, limit=limit)
    rule_health = health_summary(root)

    runtime_counts: dict[str, int] = {}
    for service in services:
        status = str(service.get("runtime_status") or "UNKNOWN").upper()
        runtime_counts[status] = runtime_counts.get(status, 0) + 1

    severity_counts: dict[str, int] = {}
    for incident in incidents:
        severity = str(incident.get("severity") or "INFO").upper()
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    posting_attention = [
        row
        for row in posting_intelligence["destinations"]
        if row["delivery_health"] in {"ATTENTION", "DEGRADED"}
        or row["needs_review"]
        or row["quarantined"]
    ]
    risk_attention = [row for row in risk_fusion["subjects"] if row["review_required"]]

    return {
        "contract_version": MISSION_CONTROL_CONTRACT_VERSION,
        "phase": "2 - Make Brain useful",
        "headline": {
            "services": len(services),
            "registered_services": registry["service_count"],
            "adapter_supported_services": adapters["supported_count"],
            "adapter_ready_services": adapters["ready_count"],
            "adapter_evidence_required": adapters["evidence_required_count"],
            "fleet_heartbeat_status": fleet_heartbeat["status"],
            "fleet_heartbeat_integrated_services": fleet_heartbeat["integrated_service_count"],
            "fleet_heartbeat_expected_services": fleet_heartbeat["expected_service_count"],
            "fleet_heartbeat_integration_coverage_percent": fleet_heartbeat["integration_coverage_percent"],
            "fleet_heartbeat_observed_coverage_percent": fleet_heartbeat["observed_coverage_percent"],
            "fleet_heartbeat_incident_candidates": fleet_heartbeat["incident_candidate_count"],
            "telemetry_status": telemetry["status"],
            "telemetry_running_services": telemetry["running_count"],
            "telemetry_fresh_running": telemetry["fresh_running_count"],
            "telemetry_late_running": telemetry["late_running_count"],
            "telemetry_attention_running": telemetry["attention_running_count"],
            "runtime_counts": runtime_counts,
            "health_unhealthy": platform_health["unhealthy_count"],
            "health_not_ready": platform_health["not_ready_count"],
            "open_incidents": len(incidents),
            "incident_severity_counts": severity_counts,
            "active_signals": len(signals),
            "ranked_decisions": decisions["decision_count"],
            "opportunities": opportunities["count"],
            "blocked_opportunities": opportunities["blocked_count"],
            "canonical_opportunities": opportunities["canonical_count"],
            "canonical_cross_domain_opportunities": opportunities["canonical_cross_domain_count"],
            "risk_fusion_status": risk_fusion["status"],
            "risk_fusion_subjects": risk_fusion["subject_count"],
            "risk_attention_subjects": len(risk_attention),
            "risk_high_subjects": sum(1 for row in risk_fusion["subjects"] if row["high_risk"]),
            "entities": graph["node_count"],
            "relationships": graph["edge_count"],
            "relationship_intelligence_status": relationship_intelligence["status"],
            "relationship_profiles": relationship_intelligence["profile_count"],
            "relationship_dormant": relationship_intelligence["state_counts"].get("DORMANT", 0),
            "relationship_cooling": relationship_intelligence["state_counts"].get("COOLING", 0),
            "group_search_intelligence_status": group_search_intelligence["status"],
            "group_activity_profiles": group_search_intelligence["group_count"],
            "posting_intelligence_status": posting_intelligence["status"],
            "posting_destinations": posting_intelligence["destination_count"],
            "posting_attention_destinations": len(posting_attention),
            "posting_uncertain_queue": posting_intelligence["queue_counts"].get("uncertain", 0),
            "trust_event_store": trust_foundation["event_store_status"],
            "canonical_subject_coverage": trust_foundation["canonical_subject_coverage"],
            "noncanonical_intelligence_subject_events": trust_foundation["noncanonical_subject_events"],
            "canonical_readiness": readiness["status"],
            "canonical_shadow_samples": readiness["canonical_inference_count"],
            "canonical_parity": readiness["parity_status"],
            "canonical_evidence_health": evidence_health["status"],
            "canonical_calibration": calibration["status"],
            "canonical_review_recommendations": canonical_recommendations["count"],
            "canonical_review_expired": canonical_lifecycle["counts"].get("EXPIRED", 0),
            "canonical_review_outcomes": canonical_feedback["recorded_outcomes"],
            "canonical_reviews_awaiting_outcome": canonical_feedback["completed_without_outcome"],
            "canonical_review_calibration": canonical_review_calibration["status"],
            "canonical_review_audit_status": canonical_review_audit["status"],
            "canonical_review_audit_events": sum(canonical_review_audit["stage_counts"].values()),
        },
        "attention": {
            "incidents": incidents,
            "unhealthy_services": platform_health["unhealthy_services"],
            "adapter_evidence_required": [
                row for row in adapters["services"] if row["status"] == "EVIDENCE_REQUIRED"
            ],
            "fleet_heartbeat_incident_candidates": fleet_heartbeat["incident_candidates"],
            "telemetry_attention_services": telemetry["attention_services"],
            "telemetry_late_services": telemetry["late_services"],
            "correlated_incident_intelligence_subjects": platform_intelligence["correlated_subjects"],
            "conflicts": decisions["conflicts"],
            "rollback_recommendations": rule_health["rollback_recommendations"],
            "blocked_opportunities": [row for row in opportunities["top_opportunities"] if row["blocked"]],
            "canonical_opportunities": opportunities["canonical_top_opportunities"],
            "risk_adjusted_canonical_opportunities": risk_adjusted_opportunities,
            "risk_review_subjects": risk_attention,
            "risk_malformed_guard_events": risk_fusion["malformed_guard_events"],
            "risk_noncanonical_guard_events_ignored": risk_fusion["noncanonical_guard_events_ignored"],
            "relationship_profiles": relationship_intelligence["profiles"],
            "relationship_malformed_events": relationship_intelligence["malformed_events"],
            "relationship_noncanonical_events_ignored": relationship_intelligence["noncanonical_events_ignored"],
            "group_activity_profiles": group_search_intelligence["groups"],
            "group_search_malformed_events": group_search_intelligence["malformed_events"],
            "group_search_noncanonical_events_ignored": group_search_intelligence["noncanonical_events_ignored"],
            "posting_destinations": posting_attention,
            "posting_malformed_rows": posting_intelligence["malformed_rows"],
            "noncanonical_intelligence_subject_events": trust_foundation["noncanonical_subject_events"],
            "canonical_readiness_reasons": list(readiness["reasons"]),
            "canonical_evidence_stale": bool(evidence_health["stale"]),
            "canonical_calibration_review_required": calibration["status"] == "REVIEW_REQUIRED",
            "canonical_review_recommendations": canonical_recommendations["recommendations"],
            "canonical_reviews_awaiting_outcome": canonical_feedback["completed_without_outcome"],
            "canonical_review_calibration_review_required": (
                canonical_review_calibration["status"] == "REVIEW_REQUIRED"
            ),
            "canonical_review_audit_malformed_rows": canonical_review_audit["malformed_rows"],
        },
        "platform": {
            "contract_version": MISSION_CONTROL_CONTRACT_VERSION,
            "revision": MISSION_CONTROL_PLATFORM_REVISION,
            "registry": registry,
            "adapters": adapters,
            "telemetry": telemetry,
            "fleet_heartbeat": fleet_heartbeat,
            "health": platform_health,
            "incident_intelligence": platform_intelligence,
        },
        "opportunities": opportunities["top_opportunities"],
        "canonical_opportunities": opportunities["canonical_top_opportunities"],
        "risk_adjusted_canonical_opportunities": risk_adjusted_opportunities,
        "risk_fusion": risk_fusion,
        "decisions": decisions["top_decisions"],
        "rule_health": rule_health,
        "trust_foundation": trust_foundation,
        "relationship_intelligence": relationship_intelligence,
        "group_search_intelligence": group_search_intelligence,
        "posting_intelligence": posting_intelligence,
        "canonical": canonical,
        "canonical_recommendations": canonical_recommendations,
        "canonical_recommendation_lifecycle": canonical_lifecycle,
        "canonical_review_feedback": canonical_feedback,
        "canonical_review_calibration": canonical_review_calibration,
        "canonical_review_audit": canonical_review_audit,
        "graph_summary": {
            "node_count": graph["node_count"],
            "edge_count": graph["edge_count"],
            "type_counts": graph["type_counts"],
        },
        "services": services,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }
