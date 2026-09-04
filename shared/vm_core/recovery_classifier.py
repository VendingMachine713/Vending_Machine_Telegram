from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
from typing import Any

from .manifests import discover_bots
from .paths import project_root
from .recovery_policy import service_recovery_policy
from .runtime_requirements import runtime_configuration_status
from .watchdog import watchdog_snapshot


@dataclass(frozen=True)
class RecoveryDecision:
    service: str
    failure_class: str
    classification: str
    action: str
    reason: str
    automatic: bool
    requires_operator: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _manifest_lifecycle(bot_dir: Path) -> dict[str, Any]:
    path = bot_dir / "BOT_MANIFEST.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    lifecycle = data.get("lifecycle")
    return lifecycle if isinstance(lifecycle, dict) else {}


def classify_finding(service: str, code: str, detail: str, *, process_alive: bool,
                     policy: dict[str, Any]) -> RecoveryDecision:
    text = f"{code} {detail}".lower()

    if any(term in text for term in ("uncertain", "delivery ambiguity", "send_timeout")):
        failure = "DELIVERY_AMBIGUITY"
    elif any(term in text for term in ("auth", "credential", "bot_token", "api_hash")):
        failure = "AUTHENTICATION"
    elif any(term in text for term in ("flood", "rate limit", "workerbusy", "telegram workers")):
        failure = "TELEGRAM_LIMIT"
    elif "session" in text:
        failure = "SESSION"
    elif any(term in text for term in ("database", "integrity", "malformed", "corrupt")):
        failure = "DATABASE_CORRUPTION"
    elif code in {"HEARTBEAT_EXPIRED", "HEARTBEAT_STALE", "HEARTBEAT_MISSING"}:
        failure = "HEARTBEAT"
    elif not process_alive:
        failure = "PROCESS_DOWN"
    else:
        failure = "UNKNOWN"

    if failure in policy.get("blocked_failure_classes", set()):
        return RecoveryDecision(service, failure, "BLOCKED", "INVESTIGATE",
                                "Failure class is explicitly blocked from automatic recovery.",
                                False, True)

    if failure == "TELEGRAM_LIMIT":
        return RecoveryDecision(service, failure, "WAIT_AND_RETRY", "WAIT",
                                "Telegram-side rate/worker pressure should cool down before retry.",
                                False, False)

    if failure == "HEARTBEAT" and process_alive:
        return RecoveryDecision(service, failure, "REVIEW_REQUIRED", "INSPECT",
                                "Process is alive but heartbeat evidence is unhealthy; restart is not yet proven safe.",
                                False, True)

    if failure == "PROCESS_DOWN":
        if policy.get("auto_restart"):
            return RecoveryDecision(service, failure, "AUTO_RECOVER", "RESTART_SERVICE",
                                    "Process is down and service policy explicitly allows restart.",
                                    True, False)
        if policy.get("auto_start"):
            return RecoveryDecision(service, failure, "AUTO_RECOVER", "START_SERVICE",
                                    "Process is down and service policy explicitly allows start.",
                                    True, False)
        return RecoveryDecision(service, failure, "REVIEW_REQUIRED", "INSPECT",
                                "Process is down but service policy does not authorize automatic lifecycle recovery.",
                                False, True)

    return RecoveryDecision(service, failure, "REVIEW_REQUIRED", "INSPECT",
                            "Evidence is insufficient for a safe automatic action.",
                            False, True)


def recovery_plan(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    watchdog = watchdog_snapshot(root)
    watch_by_service = {row["service"]: row for row in watchdog["services"]}
    decisions: list[RecoveryDecision] = []

    for bot in discover_bots(root):
        bot_dir = Path(bot.path)
        policy = service_recovery_policy(bot.folder, _manifest_lifecycle(bot_dir), root)
        runtime_cfg = runtime_configuration_status(bot_dir)
        row = watch_by_service.get(bot.folder, {})
        process_alive = bool(row.get("process_alive"))

        if not runtime_cfg.get("configured", True):
            decisions.append(RecoveryDecision(
                bot.folder, "CREDENTIALS", "BLOCKED", "CONFIGURE",
                "Required runtime configuration is missing; lifecycle recovery is blocked.",
                False, True,
            ))
            continue

        findings = row.get("findings") or []
        if not findings:
            decisions.append(RecoveryDecision(
                bot.folder, "NONE", "HEALTHY", "NONE",
                "No watchdog failure findings.", False, False,
            ))
            continue

        ranked = sorted(
            findings,
            key=lambda f: 0 if str(f.get("severity")).upper() == "ERROR" else 1,
        )
        decision = classify_finding(
            bot.folder,
            str(ranked[0].get("code") or "UNKNOWN"),
            str(ranked[0].get("detail") or ""),
            process_alive=process_alive,
            policy=policy,
        )
        decisions.append(decision)

    summary = {
        key: sum(1 for d in decisions if d.classification == key)
        for key in ("HEALTHY", "AUTO_RECOVER", "WAIT_AND_RETRY", "REVIEW_REQUIRED", "BLOCKED")
    }
    return {
        "mode": "READ_ONLY_PLAN",
        "summary": summary,
        "decisions": [d.to_dict() for d in decisions],
        "safety": {
            "mutations_performed": False,
            "telegram_delivery_retry_performed": False,
            "uncertain_delivery_retry_performed": False,
            "credential_recovery_performed": False,
        },
    }


def format_recovery_plan(plan: dict[str, Any]) -> str:
    s = plan["summary"]
    lines = [
        "=" * 78,
        " VM CORE RECOVERY CLASSIFICATION",
        "=" * 78,
        f"Healthy={s['HEALTHY']} Auto={s['AUTO_RECOVER']} Wait={s['WAIT_AND_RETRY']} "
        f"Review={s['REVIEW_REQUIRED']} Blocked={s['BLOCKED']}",
        "",
    ]
    for row in plan["decisions"]:
        lines.append(
            f"{row['service']:<28} {row['classification']:<16} {row['failure_class']} -> {row['action']}"
        )
        lines.append(f"  {row['reason']}")
    lines += ["", "Read-only plan: no recovery action has been executed."]
    return "\n".join(lines)
