from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .business_memory_adapter import collect_business_memory_signals
from .canonical_bridge import bridge_legacy_signals
from .canonical_correlation import correlate_relationship_search
from .canonical_recommendation_lifecycle import (
    canonical_review_lifecycle_summary,
    expire_canonical_review_proposals,
)
from .canonical_recommendations import (
    canonical_recommendation_summary,
    propose_canonical_reengagement_reviews,
)
from .canonical_shadow import evaluate_legacy_canonical_parity
from .intelligence_audit import audit_summary
from .paths import project_root


def run_canonical_brain_pass(*, root: Path | None = None, limit: int = 1000) -> dict[str, Any]:
    """Run one bounded canonical migration/correlation/shadow pass.

    This is the compatibility-safe shadow path. It projects Business Memory into
    aggregate chat-level signals, bridges selected VM signals into the Trust Layer,
    derives cross-bot inference, and compares that inference with the established
    legacy opportunity projection. It creates no recommendation and has no action
    execution authority.
    """
    root = root or project_root()
    business_memory = collect_business_memory_signals(root=root)
    bridge = bridge_legacy_signals(root=root, limit=limit)
    correlation = correlate_relationship_search(root=root, limit=limit)
    parity = evaluate_legacy_canonical_parity(root=root)
    return {
        "mode": "shadow",
        "business_memory": business_memory,
        "bridge": bridge,
        "correlation": correlation,
        "parity": asdict(parity),
        "audit": audit_summary(root=root, limit=limit),
        "recommendations_created": 0,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }


def run_governed_canonical_brain_pass(
    *,
    root: Path | None = None,
    limit: int = 1000,
    minimum_opportunity_score: float = 60.0,
    proposal_stale_after_hours: float = 72.0,
) -> dict[str, Any]:
    """Run one bounded canonical pass plus governed review-metadata maintenance.

    The established shadow pass remains unchanged. After it completes, obsolete
    PROPOSED canonical reviews are expired and current eligible inferences may create
    or refresh PROPOSED review recommendations. No recommendation is accepted,
    scheduled, executed or sent to Telegram by this function.
    """
    root = root or project_root()
    shadow = run_canonical_brain_pass(root=root, limit=limit)
    lifecycle = expire_canonical_review_proposals(
        root=root,
        stale_after_hours=proposal_stale_after_hours,
        minimum_opportunity_score=minimum_opportunity_score,
        limit=limit,
    )
    proposals = propose_canonical_reengagement_reviews(
        root=root,
        minimum_opportunity_score=minimum_opportunity_score,
        limit=limit,
    )
    recommendation_summary = canonical_recommendation_summary(root=root, limit=limit)
    lifecycle_summary = canonical_review_lifecycle_summary(root=root, limit=limit)
    return {
        "mode": "governed_review",
        "shadow": shadow,
        "lifecycle": lifecycle,
        "proposals": proposals,
        "recommendations": recommendation_summary,
        "recommendation_lifecycle": lifecycle_summary,
        "recommendations_created": int(proposals.get("created") or 0),
        "recommendations_refreshed": int(proposals.get("refreshed") or 0),
        "recommendations_expired": int(lifecycle.get("expired") or 0),
        "automatic_acceptance": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }
