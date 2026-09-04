from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from .canonical_health import canonical_evidence_health_summary
from .canonical_shadow import ParityPolicy, evaluate_legacy_canonical_parity
from .intelligence_audit import AuditQuery, audit_summary, query_intelligence_events
from .paths import project_root


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    minimum_canonical_inferences: int = 5
    maximum_suppressed_ratio: float = 1.0
    require_parity_pass: bool = True


@dataclass(frozen=True, slots=True)
class CanonicalReadiness:
    ready_for_recommendation_development: bool
    status: str
    reasons: tuple[str, ...]
    canonical_inference_count: int
    suppressed_inference_count: int
    suppressed_ratio: float
    parity_status: str
    recommendation_execution_enabled: bool = False
    automatic_execution: bool = False


def canonical_recommendation_readiness(
    *,
    root: Path | None = None,
    policy: ReadinessPolicy | None = None,
    parity_policy: ParityPolicy | None = None,
) -> CanonicalReadiness:
    """Assess whether canonical evidence is mature enough to *develop* recommendations.

    This gate does not create, approve, or execute a recommendation. It only reports
    whether the canonical migration has enough evidence to begin the next governed
    development stage.
    """
    root = root or project_root()
    policy = policy or ReadinessPolicy()
    parity = evaluate_legacy_canonical_parity(root=root, policy=parity_policy)
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

    ready = not reasons
    return CanonicalReadiness(
        ready_for_recommendation_development=ready,
        status="READY_FOR_GOVERNED_DEVELOPMENT" if ready else "SHADOW_EVIDENCE_REQUIRED",
        reasons=tuple(reasons),
        canonical_inference_count=count,
        suppressed_inference_count=suppressed,
        suppressed_ratio=suppressed_ratio,
        parity_status=parity.status,
        recommendation_execution_enabled=False,
        automatic_execution=False,
    )


def canonical_operator_summary(*, root: Path | None = None) -> dict[str, Any]:
    """Return one passive operator surface for canonical Brain migration health."""
    root = root or project_root()
    readiness = canonical_recommendation_readiness(root=root)
    evidence_health = canonical_evidence_health_summary(root=root)
    return {
        "canonical_readiness": asdict(readiness),
        "evidence_health": evidence_health,
        "intelligence_audit": audit_summary(root=root),
        "operator_action_required": not readiness.ready_for_recommendation_development,
        "recommended_operator_action": (
            "Collect additional shadow evidence and resolve parity mismatches before canonical recommendation development."
            if not readiness.ready_for_recommendation_development
            else "Canonical evidence gate is satisfied; recommendation development may proceed under separate governance."
        ),
        "recommendation_execution_enabled": False,
        "automatic_execution": False,
    }
