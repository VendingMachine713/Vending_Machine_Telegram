from __future__ import annotations
from pathlib import Path
import time
from typing import Any
from .paths import project_root
from .recovery import execute_recovery_plan, recovery_plan
from .events import emit
from .logging_setup import log_event


def supervise_once(root: Path | None = None, apply: bool = False) -> list[dict[str, Any]]:
    """Run one policy-gated supervisor pass.

    Recovery decisions are delegated to Recovery Intelligence so the supervisor
    cannot bypass BLOCKED/REVIEW classifications. Only SAFE_RECOVERY decisions
    can reach service start/restart functions, and the executor applies at most
    one action per pass by default with cooldown/attempt-limit protection.
    """
    root = root or project_root()
    plan = recovery_plan(root)
    execution = execute_recovery_plan(plan, root, apply=apply, max_actions=1)
    executed = {row.get("service"): row for row in execution.get("actions") or []}
    skipped = {row.get("service"): row for row in execution.get("skipped") or []}

    actions: list[dict[str, Any]] = []
    for decision in plan.get("decisions") or []:
        service = str(decision.get("service") or "unknown")
        classification = str(decision.get("classification") or "UNKNOWN")
        proposed = str(decision.get("action") or "NONE")

        if service in executed:
            result = executed[service]
            action = "restart" if proposed == "RESTART_SERVICE" else "start"
            actions.append({
                "service": service,
                "action": action,
                "classification": classification,
                "applied": bool(apply),
                "result": result.get("result"),
                "verified": result.get("verified"),
                "escalation": result.get("escalation"),
            })
            emit(
                "supervisor.recovery_requested",
                "supervisor",
                {"service": service, "classification": classification, "applied": apply},
                root,
            )
            log_event(
                "supervisor_recovery",
                level="WARN",
                data={"service": service, "classification": classification, "applied": apply},
                root=root,
            )
        elif service in skipped:
            actions.append({
                "service": service,
                "action": "none",
                "classification": classification,
                "reason": skipped[service].get("reason"),
                "recovery_gate": skipped[service].get("history"),
            })
        else:
            actions.append({
                "service": service,
                "action": "none",
                "classification": classification,
                "reason": decision.get("reason"),
                "proposed_action": proposed,
            })

    # Intelligence refresh is deliberately isolated from recovery control. A
    # collector/read-model problem must never prevent normal supervisor actions.
    try:
        from .intelligence import materialize_intelligence
        materialize_intelligence(root)
    except Exception as exc:
        emit(
            "incident.intelligence_refresh_failed",
            "supervisor",
            {"summary": "VM Intelligence refresh failed", "error_type": type(exc).__name__},
            root,
            severity="WARNING",
            subject_type="service",
            subject_id="VM_Intelligence",
        )
        log_event(
            "intelligence_refresh_failed",
            level="WARN",
            data={"error_type": type(exc).__name__},
            root=root,
        )
    return actions


def supervise_loop(root: Path | None = None, apply: bool = False, interval_seconds: int = 60) -> None:
    root = root or project_root()
    while True:
        supervise_once(root, apply=apply)
        time.sleep(max(10, interval_seconds))
