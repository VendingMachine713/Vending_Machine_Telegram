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
from .health_contract import health_snapshot
from .opportunity_intelligence import opportunity_summary
from .paths import project_root
from .platform_aggregation import incident_intelligence_snapshot
from .platform_registry import service_registry
from .rule_health import health_summary

MISSION_CONTROL_CONTRACT_VERSION = 4


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
    graph = entity_graph(root, limit=max(100, limit * 10))
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

    return {
        "contract_version": MISSION_CONTROL_CONTRACT_VERSION,
        "phase": "2 - Make Brain useful",
        "headline": {
            "services": len(services),
            "registered_services": registry["service_count"],
            "runtime_counts": runtime_counts,
            "health_unhealthy": platform_health["unhealthy_count"],
            "health_not_ready": platform_health["not_ready_count"],
            "open_incidents": len(incidents),
            "incident_severity_counts": severity_counts,
            "active_signals": len(signals),
            "ranked_decisions": decisions["decision_count"],
            "opportunities": opportunities["count"],
            "blocked_opportunities": opportunities["blocked_count"],
            "entities": graph["node_count"],
            "relationships": graph["edge_count"],
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
            "correlated_incident_intelligence_subjects": platform_intelligence["correlated_subjects"],
            "conflicts": decisions["conflicts"],
            "rollback_recommendations": rule_health["rollback_recommendations"],
            "blocked_opportunities": [row for row in opportunities["top_opportunities"] if row["blocked"]],
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
            "registry": registry,
            "health": platform_health,
            "incident_intelligence": platform_intelligence,
        },
        "opportunities": opportunities["top_opportunities"],
        "decisions": decisions["top_decisions"],
        "rule_health": rule_health,
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
