from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical_bridge import bridge_legacy_signals
from .canonical_correlation import correlate_relationship_search
from .intelligence_audit import audit_summary
from .paths import project_root


def run_canonical_brain_pass(*, root: Path | None = None, limit: int = 1000) -> dict[str, Any]:
    """Run one bounded canonical Brain migration/correlation pass.

    This pass bridges selected existing VM signals into the Trust Layer and derives
    the first cross-bot inference. It creates no recommendation and has no action
    execution authority.
    """
    root = root or project_root()
    bridge = bridge_legacy_signals(root=root, limit=limit)
    correlation = correlate_relationship_search(root=root, limit=limit)
    return {
        "bridge": bridge,
        "correlation": correlation,
        "audit": audit_summary(root=root, limit=limit),
        "recommendations_created": 0,
        "automatic_execution": False,
    }
