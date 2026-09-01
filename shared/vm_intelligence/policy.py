from __future__ import annotations
from dataclasses import dataclass

BLOCKED = {
    "delete_master_data", "expose_credentials", "change_identity",
    "weaken_security", "remove_backups", "irreversible_migration"
}
AUTO_ALLOWED = {
    "run_tests", "gather_diagnostics", "generate_report", "create_backup",
    "rotate_logs", "restart_unhealthy_process", "retry_transient_operation"
}

@dataclass(frozen=True)
class Decision:
    action: str
    authority: str
    reason: str

class PolicyEngine:
    """Safety gate for future autonomous actions."""
    def decide(self, action: str, *, reversible: bool, risk: str, confidence: float) -> Decision:
        if action in BLOCKED:
            return Decision(action, "blocked", "Protected action requires explicit user control.")
        if action in AUTO_ALLOWED and reversible and risk == "low" and confidence >= .90:
            return Decision(action, "automatic", "Allow-listed, reversible, low-risk, high-confidence action.")
        return Decision(action, "approval", "Action is outside the automatic safety envelope.")
