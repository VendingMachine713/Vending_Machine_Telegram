from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .business_memory_adapter import collect_business_memory_signals
from .canonical_bridge import bridge_legacy_signals
from .canonical_correlation import correlate_relationship_search
from .canonical_shadow import evaluate_legacy_canonical_parity
from .intelligence_audit import audit_summary
from .paths import project_root


def run_canonical_brain_pass(*, root: Path | None = None, limit: int = 1000) -> dict[str, Any]:
    """Run one bounded canonical Brain migration/correlation/shadow pass.

    This pass projects Business Memory into aggregate chat-level signals, bridges
    selected VM signals into the Trust Layer, derives cross-bot inference, and
    compares that inference with the established legacy opportunity projection.
    It creates no recommendation and has no action execution authority.
    """
    root = root or project_root()
    business_memory = collect_business_memory_signals(root=root)
    bridge = bridge_legacy_signals(root=root, limit=limit)
    correlation = correlate_relationship_search(root=root, limit=limit)
    parity = evaluate_legacy_canonical_parity(root=root)
    return {
        "business_memory": business_memory,
        "bridge": bridge,
        "correlation": correlation,
        "parity": asdict(parity),
        "audit": audit_summary(root=root, limit=limit),
        "recommendations_created": 0,
        "automatic_execution": False,
    }
