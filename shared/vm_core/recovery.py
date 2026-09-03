from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .manifests import discover_bots
from .paths import project_root
from .services import service_status


ATTENTION_STATES = {"FAILED", "STOPPED", "DOWN", "ERROR", "STALE", "DEGRADED"}
SAFE_ACTIONS = {"START_SERVICE", "RESTART_SERVICE"}
BLOCKED_HINTS = ("uncertain", "telegram", "session", "credential", "auth", "login", "flood", "rate limit")


@dataclass(slots=True)
class RecoveryDecision:
    service: str
    classification: str
    action: str
    reason: str
    confidence: float
    automatic: bool = False
    requires_operator: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _manifest_policy(bot_dir: Path) -> dict[str, bool]:
    import json

    path = bot_dir / "BOT_MANIFEST.json"
    if not path.is_file():
        return {"auto_start": False, "auto_restart": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        lifecycle = data.get("lifecycle") or {}
        return {
            "auto_start": bool(lifecycle.get("auto_start", False)),
            "auto_restart": bool(lifecycle.get("auto_restart", False)),
        }
    except Exception:
        return {"auto_start": False, "auto_restart": False}


def classify_service(row: dict[str, Any], policy: dict[str, bool]) -> RecoveryDecision:
    name = str(row.get("name") or row.get("service") or "unknown")
    alive = bool(row.get("process_alive"))
    status = str(row.get("runtime_status") or row.get("status") or "UNKNOWN").upper()
    detail = " ".join(str(row.get(k) or "") for k in ("last_error", "detail", "message")).lower()

    if alive:
        return RecoveryDecision(name, "HEALTHY", "NONE", "Process is alive.", 1.0)

    if any(hint in detail for hint in BLOCKED_HINTS):
        return RecoveryDecision(
            name,
            "BLOCKED",
            "INVESTIGATE",
            "Failure evidence may involve delivery ambiguity, Telegram limits, authentication, or credentials; automatic recovery is unsafe.",
            0.95,
            automatic=False,
            requires_operator=True,
        )

    if status in ATTENTION_STATES and policy.get("auto_restart"):
        return RecoveryDecision(
            name,
            "SAFE_RECOVERY",
            "RESTART_SERVICE",
            "Service is not alive and its manifest explicitly permits automatic restart.",
            0.95,
            automatic=True,
        )

    if status in ATTENTION_STATES and policy.get("auto_start"):
        return RecoveryDecision(
            name,
            "SAFE_RECOVERY",
            "START_SERVICE",
            "Service is not alive and its manifest explicitly permits automatic start.",
            0.9,
            automatic=True,
        )

    if status in ATTENTION_STATES:
        return RecoveryDecision(
            name,
            "REVIEW",
            "INVESTIGATE",
            "Service is unhealthy but its manifest does not authorize automatic recovery.",
            0.85,
            requires_operator=True,
        )

    return RecoveryDecision(
        name,
        "UNKNOWN",
        "OBSERVE",
        "Runtime evidence is insufficient for a safe recovery decision.",
        0.5,
    )


def recovery_plan(root: Path | None = None) -> dict[str, Any]:
    """Build a read-only, policy-gated recovery plan.

    This function never starts, stops, restarts, retries or mutates a bot. It only
    classifies evidence and proposes actions. Consequential operations remain in
    the existing service/supervisor layer and require their normal mutation gate.
    """
    root = root or project_root()
    states = {str(row.get("name")): row for row in service_status(root)}
    decisions: list[RecoveryDecision] = []

    for bot in discover_bots(root):
        if bot.classification == "PLACEHOLDER":
            continue
        row = states.get(bot.folder, {"name": bot.folder, "runtime_status": "UNKNOWN", "process_alive": False})
        decisions.append(classify_service(row, _manifest_policy(Path(bot.path))))

    automatic = [d for d in decisions if d.automatic and d.action in SAFE_ACTIONS]
    operator = [d for d in decisions if d.requires_operator]
    blocked = [d for d in decisions if d.classification == "BLOCKED"]
    healthy = [d for d in decisions if d.classification == "HEALTHY"]

    return {
        "mode": "READ_ONLY_PLAN",
        "summary": {
            "services": len(decisions),
            "healthy": len(healthy),
            "automatic_candidates": len(automatic),
            "operator_attention": len(operator),
            "blocked": len(blocked),
        },
        "decisions": [d.to_dict() for d in decisions],
        "safety": {
            "mutations_performed": False,
            "uncertain_delivery_auto_retry": False,
            "credential_or_auth_recovery": False,
        },
    }


def format_recovery_plan(plan: dict[str, Any]) -> str:
    s = plan.get("summary") or {}
    lines = [
        "VM RECOVERY INTELLIGENCE",
        f"Mode: {plan.get('mode', 'UNKNOWN')}",
        (
            f"Services: {s.get('services', 0)} | Healthy: {s.get('healthy', 0)} | "
            f"Safe recovery candidates: {s.get('automatic_candidates', 0)} | "
            f"Needs operator: {s.get('operator_attention', 0)} | Blocked: {s.get('blocked', 0)}"
        ),
        "",
    ]
    for row in plan.get("decisions") or []:
        lines.append(
            f"{row.get('classification','UNKNOWN'):<14} {row.get('service','unknown')} -> {row.get('action','NONE')}"
        )
        lines.append(f"  {row.get('reason','')}")
    lines.extend([
        "",
        "Safety: planning only; no service restart, queue retry, campaign change, or Telegram action is performed.",
    ])
    return "\n".join(lines)
