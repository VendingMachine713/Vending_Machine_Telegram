from __future__ import annotations

from pathlib import Path
from typing import Any

from .heartbeat import heartbeat_snapshot
from .paths import project_root
from .recovery_policy import load_recovery_policy
from .recovery_state import RecoveryHistory
from .services import restart_service, service_status, start_service


SAFE_ACTIONS = {"START_SERVICE", "RESTART_SERVICE"}


def verify_service(service: str, root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    runtime = next((r for r in service_status(root) if str(r.get("name")) == service), None)
    if runtime is None:
        return {"verified": False, "reason": "service_not_found"}
    alive = bool(runtime.get("process_alive"))
    heartbeats = {h["service"]: h for h in heartbeat_snapshot(root)["heartbeats"]}
    hb = heartbeats.get(service)
    heartbeat_ok = hb is None or hb.get("freshness") in {"FRESH", "STALE"}
    return {
        "verified": bool(alive and heartbeat_ok),
        "process_alive": alive,
        "runtime_status": runtime.get("runtime_status"),
        "heartbeat_freshness": hb.get("freshness") if hb else None,
        "reason": "ok" if alive and heartbeat_ok else "post_recovery_verification_failed",
    }


def execute_recovery_plan(plan: dict[str, Any], root: Path | None = None, *,
                          apply: bool = False, history: RecoveryHistory | None = None) -> dict[str, Any]:
    root = root or project_root()
    policy = load_recovery_policy(root)
    history = history or RecoveryHistory(root)
    allowed_apply = bool(apply and policy.get("enabled") and policy.get("apply_safe"))
    limit = max(0, int(policy.get("max_actions_per_pass", 1)))
    actions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    candidates = [
        row for row in plan.get("decisions", [])
        if row.get("classification") == "AUTO_RECOVER"
        and row.get("automatic") is True
        and row.get("action") in SAFE_ACTIONS
    ]

    for row in candidates:
        if len(actions) >= limit:
            skipped.append({"service": row.get("service"), "reason": "pass_limit"})
            continue
        service = str(row.get("service"))
        gate = history.status(service)
        if gate["limited"]:
            skipped.append({"service": service, "reason": "attempt_limit", "history": gate})
            continue
        if gate["cooling_down"]:
            skipped.append({"service": service, "reason": "cooldown", "history": gate})
            continue

        action = str(row.get("action"))
        if action == "START_SERVICE":
            result = start_service(service, root, dry_run=not allowed_apply)
        else:
            result = restart_service(service, root, dry_run=not allowed_apply)

        verification = {"verified": False, "reason": "dry_run"}
        if allowed_apply:
            verification = verify_service(service, root)
            history.record_attempt(service, action=action, success=bool(result.get("ok")) and bool(verification["verified"]))
            if verification["verified"]:
                history.reset(service)

        actions.append({
            "service": service,
            "action": action,
            "applied": allowed_apply,
            "result": result,
            "verification": verification,
        })

    return {
        "mode": "APPLY_SAFE_RECOVERY" if allowed_apply else "DRY_RUN",
        "policy_enabled": bool(policy.get("enabled")),
        "policy_apply_safe": bool(policy.get("apply_safe")),
        "candidate_count": len(candidates),
        "actions": actions,
        "skipped": skipped,
        "operator_escalation_required": any(
            item.get("reason") == "attempt_limit" for item in skipped
        ) or any(
            item["applied"] and not item["verification"].get("verified") for item in actions
        ),
        "safety": {
            "blocked_or_review_actions_executed": False,
            "telegram_delivery_retry_performed": False,
            "uncertain_delivery_retry_performed": False,
            "crash_loop_guard_enabled": True,
            "post_recovery_verification_enabled": True,
        },
    }
