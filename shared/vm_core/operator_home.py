from __future__ import annotations

from typing import Any


def _count(snapshot: dict[str, Any], key: str) -> int:
    value = snapshot.get("headline", {}).get(key, 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def operator_home(snapshot: dict[str, Any]) -> str:
    """Render a compact, read-only operator home screen from Mission Control."""
    headline = snapshot.get("headline", {})

    unhealthy = _count(snapshot, "health_unhealthy")
    not_ready = _count(snapshot, "health_not_ready")
    incidents = _count(snapshot, "open_incidents")
    telemetry_attention = _count(snapshot, "telemetry_attention_running")
    heartbeat_candidates = _count(snapshot, "fleet_heartbeat_incident_candidates")

    risk_reviews = _count(snapshot, "risk_attention_subjects")
    posting_attention = _count(snapshot, "posting_attention_destinations")
    awaiting_outcome = _count(snapshot, "canonical_reviews_awaiting_outcome")
    group_audit_attention = _count(snapshot, "group_member_audit_attention_groups")

    needs_attention = any(
        (
            unhealthy,
            not_ready,
            incidents,
            telemetry_attention,
            heartbeat_candidates,
            risk_reviews,
            posting_attention,
            awaiting_outcome,
            group_audit_attention,
        )
    )
    overall = "ATTENTION" if needs_attention else "HEALTHY"

    registered = _count(snapshot, "registered_services")
    running = _count(snapshot, "telemetry_running_services")
    expected = _count(snapshot, "fleet_heartbeat_expected_services")

    lines = [
        "=" * 60,
        " VM MISSION CONTROL - OPERATOR HOME",
        "=" * 60,
        f"SYSTEM: {overall}",
        "",
        "SYSTEM HEALTH",
        f"- Registered services: {registered}",
        f"- Running services observed: {running}/{expected or registered}",
        f"- Unhealthy services: {unhealthy}",
        f"- Services not ready: {not_ready}",
        f"- Open incidents: {incidents}",
        f"- Heartbeat incident candidates: {heartbeat_candidates}",
        "",
        "ATTENTION REQUIRED",
    ]

    attention_items: list[str] = []
    if unhealthy:
        attention_items.append(f"{unhealthy} unhealthy service(s)")
    if not_ready:
        attention_items.append(f"{not_ready} service(s) not ready")
    if incidents:
        attention_items.append(f"{incidents} open incident(s)")
    if telemetry_attention:
        attention_items.append(
            f"{telemetry_attention} running service(s) need telemetry attention"
        )
    if heartbeat_candidates:
        attention_items.append(
            f"{heartbeat_candidates} heartbeat incident candidate(s)"
        )
    if risk_reviews:
        attention_items.append(f"{risk_reviews} risk subject(s) need review")
    if posting_attention:
        attention_items.append(
            f"{posting_attention} posting destination(s) need review"
        )
    if awaiting_outcome:
        attention_items.append(
            f"{awaiting_outcome} completed review(s) await outcome evidence"
        )
    if group_audit_attention:
        attention_items.append(
            f"{group_audit_attention} group member audit(s) need review"
        )

    if attention_items:
        lines.extend(f"- {item}" for item in attention_items)
    else:
        lines.append("- Nothing currently requires operator attention.")

    lines.extend(
        [
            "",
            "INTELLIGENCE",
            f"- Opportunities: {_count(snapshot, 'opportunities')}",
            f"- Canonical opportunities: {_count(snapshot, 'canonical_opportunities')}",
            f"- Ranked decisions: {_count(snapshot, 'ranked_decisions')}",
            f"- Relationship profiles: {_count(snapshot, 'relationship_profiles')}",
            f"- Cooling relationships: {_count(snapshot, 'relationship_cooling')}",
            f"- Dormant relationships: {_count(snapshot, 'relationship_dormant')}",
            f"- Group activity profiles: {_count(snapshot, 'group_activity_profiles')}",
            f"- Audited group members: {_count(snapshot, 'group_member_audited_members')}",
            "",
            "BRAIN / GOVERNANCE",
            f"- Canonical readiness: {headline.get('canonical_readiness', 'UNKNOWN')}",
            f"- Evidence health: {headline.get('canonical_evidence_health', 'UNKNOWN')}",
            f"- Review calibration: {headline.get('canonical_review_calibration', 'UNKNOWN')}",
            f"- Audit status: {headline.get('canonical_review_audit_status', 'UNKNOWN')}",
            "",
            "SAFETY BOUNDARY",
            f"- Automatic acceptance: {'ON' if snapshot.get('automatic_acceptance') else 'OFF'}",
            f"- Automatic execution: {'ON' if snapshot.get('automatic_execution') else 'OFF'}",
            f"- External action authority: {'ON' if snapshot.get('external_action_authority') else 'OFF'}",
            "",
            "Use the full Mission Control JSON only when detailed investigation is needed.",
        ]
    )
    return "\n".join(lines)
