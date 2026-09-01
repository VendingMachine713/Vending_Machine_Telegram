from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backup_manager import BackupManager
from database import Database, utcnow


class MaintenanceEngine:
    """Safe self-healing maintenance and operational exception checks."""

    def __init__(self, db: Database, backup_dir: Path | None = None, integration=None):
        self.db = db
        self.backup_dir = Path(backup_dir or db.path.parent / "backups")
        self.backups = BackupManager(db, self.backup_dir)
        self.integration = integration

    @staticmethod
    def _age_hours(value: str | None):
        if not value:
            return None
        try:
            return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds() / 3600)
        except Exception:
            return None

    def check(self):
        findings = []
        integrity = self.db.integrity_check()
        if integrity != ["ok"]:
            findings.append({"severity": "critical", "code": "sqlite_integrity", "detail": ", ".join(integrity[:3]), "remediable": False})

        latest = self.db.one("SELECT * FROM backup_audit ORDER BY id DESC LIMIT 1")
        if not latest:
            findings.append({"severity": "high", "code": "backup_missing", "detail": "No verified backup audit exists", "remediable": True})
        else:
            verified = self.backups.verify_record(latest)
            if verified["status"] != "verified":
                findings.append({"severity": "critical", "code": "backup_invalid", "detail": verified.get("reason", "Backup verification failed"), "remediable": True})
            age = self._age_hours(latest["created_at"])
            if age is not None and age > 36:
                findings.append({"severity": "medium", "code": "backup_stale", "detail": f"Latest backup is {age:.1f}h old", "remediable": True})

        backlog = self.db.one(
            "SELECT COUNT(*) total,SUM(CASE WHEN status='retry' THEN 1 ELSE 0 END) retrying,COALESCE(MAX(attempt_count),0) max_attempts FROM integration_events WHERE status IN ('pending','retry')"
        )
        if int(backlog["retrying"] or 0) >= 10 or int(backlog["max_attempts"] or 0) >= 5:
            findings.append({"severity": "medium", "code": "integration_retry", "detail": f"{backlog['retrying'] or 0} retrying; max attempts {backlog['max_attempts'] or 0}", "remediable": True})

        last_maint = self.db.meta("last_intelligence_maintenance")
        age = self._age_hours(last_maint)
        if age is not None and age > 12:
            findings.append({"severity": "high", "code": "intelligence_stale", "detail": f"Intelligence maintenance is {age:.1f}h old", "remediable": False})

        return findings

    def run_safe(self, allow_backup: bool = True):
        before = self.check()
        actions = []
        codes = {f["code"] for f in before}

        if allow_backup and codes & {"backup_missing", "backup_stale", "backup_invalid"}:
            result = self.backups.create("self_heal")
            actions.append({"action": "create_verified_backup", "status": result["status"], "detail": result["path"]})

        if "integration_retry" in codes and self.integration:
            result = self.integration.export_all()
            actions.append({"action": "retry_integration_export", "status": "ok", "detail": f"events={result['events']} contacts={result['contacts']}"})

        # Always-safe local DB maintenance.
        self.db.optimize()
        self.db.checkpoint(truncate=False)
        actions.append({"action": "sqlite_optimize_checkpoint", "status": "ok", "detail": "PRAGMA optimize + passive checkpoint"})

        after = self.check()
        status = "pass" if not after else ("warn" if not any(f["severity"] == "critical" for f in after) else "critical")
        self.db.execute(
            """INSERT INTO maintenance_runs(status,findings_before,actions_json,findings_after,created_at)
               VALUES (?,?,?,?,?)""",
            (status, __import__("json").dumps(before), __import__("json").dumps(actions), __import__("json").dumps(after), utcnow()),
        )
        if self.integration and after:
            self.integration.emit("maintenance_warning", None, {"status": status, "findings": after[:10]})
        return {"status": status, "before": before, "actions": actions, "after": after}
