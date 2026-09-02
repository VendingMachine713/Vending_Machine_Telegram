from __future__ import annotations

from pathlib import Path
from typing import Any

from .db import PlatformDB
from .decision_engine import decision_summary
from .entity_graph import entity_graph
from .opportunity_intelligence import opportunity_summary
from .paths import project_root
from .rule_health import health_summary


def mission_control(root: Path | None = None, *, limit: int = 20) -> dict[str, Any]:
    """Return one passive, operator-oriented snapshot of VM Brain state."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    services = db.services()
    incidents = db.incidents(limit=limit, status="OPEN")
    signals = db.signals(limit=limit, status="ACTIVE")
    decisions = decision_summary(root, limit=limit)
    opportunities = opportunity_summary(root, limit=limit)
    graph = entity_graph(root, limit=max(100, limit * 10))

    runtime_counts: dict[str, int] = {}
    for service in services:
        status = str(service.get("runtime_status") or "UNKNOWN").upper()
        runtime_counts[status] = runtime_counts.get(status, 0) + 1

    severity_counts: dict[str, int] = {}
    for incident in incidents:
        severity = str(incident.get("severity") or "INFO").upper()
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    return {
        "phase": "2 - Make Brain useful",
        "headline": {
            "services": len(services),
            "runtime_counts": runtime_counts,
            "open_incidents": len(incidents),
            "incident_severity_counts": severity_counts,
            "active_signals": len(signals),
            "ranked_decisions": decisions["decision_count"],
            "opportunities": opportunities["count"],
            "blocked_opportunities": opportunities["blocked_count"],
            "entities": graph["node_count"],
            "relationships": graph["edge_count"],
        },
        "attention": {
            "incidents": incidents,
            "conflicts": decisions["conflicts"],
            "rollback_recommendations": health_summary(root)["rollback_recommendations"],
            "blocked_opportunities": [row for row in opportunities["top_opportunities"] if row["blocked"]],
        },
        "opportunities": opportunities["top_opportunities"],
        "decisions": decisions["top_decisions"],
        "rule_health": health_summary(root),
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
