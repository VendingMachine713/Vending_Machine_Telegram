from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from .canonical_calibration import canonical_calibration_summary
from .canonical_health import canonical_evidence_health_summary
from .canonical_shadow import ParityPolicy, evaluate_legacy_canonical_parity
from .intelligence_audit import AuditQuery, audit_summary, query_intelligence_events
from .paths import project_root


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    minimum_canonical_inferences: int = 5
    maximum_suppressed_ratio: float = 1.0
    require_parity_pass: bool = True
    require_fresh_evidence: bool = True
    stale_after_hours: float = 72.0
    require_acceptable_calibration_when_sufficient: bool = True
    minimum_calibration_outcomes: int = 8


@dataclass(frozen=True, slots=True)
class CanonicalReadiness:
    ready_for_recommendation_development: bool
    status: str
    reasons: tuple[str, ...]
    canonical_inference_count: int
    suppressed_inference_count: int
    suppressed_ratio: float
    parity_status: str
    evidence_health_status: str
    calibration_status: str
    calibration_known_outcomes: int
    recommendation_execution_enabled: bool = False
    automatic_execution: bool = False


def canonical_recommendation_readiness(
    *,
    root: Path | None = None,
    policy: ReadinessPolicy | None = None,
    parity_policy: ParityPolicy | None = None,
) -> CanonicalReadiness:
    """Assess whether canonical evidence is mature enough to *develop* recommendations.

    Promotion requires enough canonical subjects, legacy/canonical parity, fresh
    evidence, acceptable suppression behavior, and—once enough verified outcomes
    exist—no calibration review hold. This function creates no recommendation and
    grants no execution authority.
    """
    root = root or project_root()
    policy = policy or ReadinessPolicy()
    parity = evaluate_legacy_canonical_parity(root=root, policy=parity_policy)
    evidence_health = canonical_evidence_health_summary(
        root=root,
        stale_after_hours=max(1.0, float(policy.stale_after_hours)),
    )
    calibration = canonical_calibration_summary(root=root)
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix="intelligence.inference.relationship_reengagement_opportunity",
            source="vm_core",
            subject_type="chat",
            limit=5000,
        ),
        root=root,
    )

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        subject = str(row.get("subject_id") or "").strip()
        if subject and subject not in latest:
            latest[subject] = row

    suppressed = 0
    for row in latest.values():
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        attributes = payload.get("attributes") if isinstance(payload, dict) else None
        if isinstance(attributes, dict) and bool(attributes.get("suppressed")):
            suppressed += 1

    count = len(latest)
    suppressed_ratio = suppressed / count if count else 0.0
    reasons: list[str] = []
    minimum = max(1, int(policy.minimum_canonical_inferences))
    if count < minimum:
        reasons.append("insufficient_shadow_samples")
    if policy.require_parity_pass and not parity.passed:
        reasons.append("legacy_canonical_parity_not_passed")
    if suppressed_ratio > max(0.0, min(1.0, float(policy.maximum_suppressed_ratio))):
        reasons.append("suppressed_ratio_exceeded")
    if policy.require_fresh_evidence and bool(evidence_health.get("stale")):
        reasons.append("canonical_evidence_stale")

    known_outcomes = int(calibration.get("known_binary_outcomes") or 0)
    calibration_minimum = max(1, int(policy.minimum_calibration_outcomes))
    if (
        policy.require_acceptable_calibration_when_sufficient
        and known_outcomes >= calibration_minimum
        and str(calibration.get("status") or "") == "REVIEW_REQUIRED"
    ):
        reasons.append("canonical_calibration_review_required")

    ready = not reasons
    return CanonicalReadiness(
        ready_for_recommendation_development=ready,
        status="READY_FOR_GOVERNED_DEVELOPMENT" if ready else "SHADOW_EVIDENCE_REQUIRED",
        reasons=tuple(reasons),
        canonical_inference_count=count,
        suppressed_inference_count=suppressed,
        suppressed_ratio=suppressed_ratio,
        parity_status=parity.status,
        evidence_health_status=str(evidence_health.get("status") or "NO_EVIDENCE"),
        calibration_status=str(calibration.get("status") or "INSUFFICIENT_DATA"),
        calibration_known_outcomes=known_outcomes,
        recommendation_execution_enabled=False,
        automatic_execution=False,
    )


def canonical_operator_summary(*, root: Path | None = None) -> dict[str, Any]:
    """Return one passive operator surface for canonical Brain migration health."""
    root = root or project_root()
    readiness = canonical_recommendation_readiness(root=root)
    evidence_health = canonical_evidence_health_summary(root=root)
    calibration = canonical_calibration_summary(root=root)
    return {
        "canonical_readiness": asdict(readiness),
        "evidence_health": evidence_health,
        "calibration": calibration,
        "intelligence_audit": audit_summary(root=root),
        "operator_action_required": not readiness.ready_for_recommendation_development,
        "recommended_operator_action": (
            "Collect fresh shadow evidence and resolve parity or calibration holds before canonical recommendation development."
            if not readiness.ready_for_recommendation_development
            else "Canonical evidence gate is satisfied; recommendation development may proceed under separate governance."
        ),
        "recommendation_execution_enabled": False,
        "automatic_execution": False,
    }
