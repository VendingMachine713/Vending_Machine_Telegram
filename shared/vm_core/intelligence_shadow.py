from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .intelligence_replay import ReplayComparison, compare_replay


@dataclass(frozen=True, slots=True)
class ShadowPolicy:
    max_added: int = 50
    max_removed: int = 50
    max_change_ratio: float = 0.25
    require_baseline: bool = True


@dataclass(frozen=True, slots=True)
class ShadowEvaluation:
    passed: bool
    status: str
    reasons: tuple[str, ...]
    comparison: ReplayComparison
    change_ratio: float
    automatic_execution: bool = False


def evaluate_shadow(
    baseline: Iterable[dict[str, Any]],
    candidate: Iterable[dict[str, Any]],
    *,
    policy: ShadowPolicy | None = None,
) -> ShadowEvaluation:
    """Evaluate candidate Brain output against a baseline without executing actions.

    This is a release-quality gate for intelligence behavior, not an authority grant.
    A passing result means the observed delta stays within the configured shadow
    budget; it never permits Telegram actions or recommendation execution.
    """
    policy = policy or ShadowPolicy()
    comparison = compare_replay(baseline, candidate)
    changed = len(comparison.added_fingerprints) + len(comparison.removed_fingerprints)
    denominator = max(1, comparison.baseline_count)
    change_ratio = changed / denominator

    reasons: list[str] = []
    if policy.require_baseline and comparison.baseline_count == 0:
        reasons.append("baseline_required")
    if len(comparison.added_fingerprints) > max(0, int(policy.max_added)):
        reasons.append("added_budget_exceeded")
    if len(comparison.removed_fingerprints) > max(0, int(policy.max_removed)):
        reasons.append("removed_budget_exceeded")
    if change_ratio > max(0.0, float(policy.max_change_ratio)):
        reasons.append("change_ratio_exceeded")

    passed = not reasons
    return ShadowEvaluation(
        passed=passed,
        status="PASS" if passed else "REVIEW_REQUIRED",
        reasons=tuple(reasons),
        comparison=comparison,
        change_ratio=change_ratio,
        automatic_execution=False,
    )
