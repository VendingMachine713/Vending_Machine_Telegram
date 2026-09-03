from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .paths import project_root
from .recovery import execute_recovery_plan, recovery_plan
from .recovery_policy import load_recovery_policy


def autopilot_once(root: Path | None = None, *, force_observe: bool = False) -> dict[str, Any]:
    """Run one bounded recovery-autopilot cycle.

    The central policy defaults to disabled/read-only. Even when enabled, apply
    mode must also be explicitly enabled in the same policy. Recovery execution
    remains constrained by Recovery Intelligence classifications, cooldowns,
    attempt limits, post-action verification and the per-pass action cap.
    """
    root = root or project_root()
    policy = load_recovery_policy(root)
    plan = recovery_plan(root)
    enabled = bool(policy.get("enabled"))
    apply_safe = bool(policy.get("apply_safe")) and enabled and not force_observe
    max_actions = int(policy.get("max_actions_per_pass", 1))

    execution = execute_recovery_plan(
        plan,
        root,
        apply=apply_safe,
        max_actions=max_actions,
    )
    return {
        "mode": "ACTIVE_SAFE_RECOVERY" if apply_safe else "OBSERVE_ONLY",
        "policy_enabled": enabled,
        "apply_safe": apply_safe,
        "interval_seconds": int(policy.get("interval_seconds", 60)),
        "max_actions_per_pass": max_actions,
        "plan": plan,
        "execution": execution,
    }


def autopilot_loop(
    root: Path | None = None,
    *,
    force_observe: bool = False,
    stop: Callable[[], bool] | None = None,
) -> None:
    root = root or project_root()
    while True:
        result = autopilot_once(root, force_observe=force_observe)
        if stop and stop():
            return
        time.sleep(max(15, int(result.get("interval_seconds", 60))))
