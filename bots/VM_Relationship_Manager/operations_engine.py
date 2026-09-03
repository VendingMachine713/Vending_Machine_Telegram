from __future__ import annotations

import json
from datetime import datetime, timezone

from database import Database, utcnow


class OperationsEngine:
    """Compact operational SLO score for passive production operation."""

    def __init__(self, db: Database, backup_manager=None, integration=None):
        self.db = db
        self.backups = backup_manager
        self.integration = integration

    @staticmethod
    def _age_minutes(value: str | None):
        if not value:
            return None
        try:
            return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds() / 60)
        except Exception:
            return None

    def capture(self, run_integrity: bool = False):
        score = 100
        components = {}

        heartbeat = self.db.meta("last_heartbeat")
        hb_age = self._age_minutes(heartbeat)
        if hb_age is None:
            components["heartbeat"] = {"status": "learning", "age_min": None}
            score -= 5
        elif hb_age > 15:
            components["heartbeat"] = {"status": "stale", "age_min": round(hb_age, 1)}
            score -= 30
        else:
            components["heartbeat"] = {"status": "ok", "age_min": round(hb_age, 1)}

        for component, max_age, penalty in (("telegram_monitor", 20, 30), ("scheduler", 30, 25), ("admin_bot", 30, 20)):
            row = self.db.one("SELECT status,created_at FROM bot_health WHERE component=? ORDER BY id DESC LIMIT 1", (component,))
            age = self._age_minutes(row["created_at"]) if row else None
            if not row:
                components[component] = {"status": "learning", "age_min": None}
                score -= 5
                continue
            status = str(row["status"] or "unknown")
            ok = status in {"ok", "online", "starting"} and (age is None or age <= max_age)
            components[component] = {"status": "ok" if ok else status, "age_min": round(age, 1) if age is not None else None}
            if not ok:
                score -= penalty

        backup = self.db.one("SELECT * FROM backup_audit ORDER BY id DESC LIMIT 1")
        if backup:
            age_h = (self._age_minutes(backup["created_at"]) or 0) / 60
            verified = str(backup["integrity_status"] or "").lower() in {"verified", "ok"}
            components["backup"] = {"status": "ok" if verified and age_h <= 36 else "stale_or_unverified", "age_h": round(age_h, 1)}
            if not verified:
                score -= 25
            elif age_h > 36:
                score -= 10
        else:
            components["backup"] = {"status": "missing", "age_h": None}
            score -= 20

        backlog = self.integration.backlog() if self.integration else self.db.one(
            "SELECT COUNT(*) total,SUM(CASE WHEN status='retry' THEN 1 ELSE 0 END) retrying,COALESCE(MAX(attempt_count),0) max_attempts FROM integration_events WHERE status IN ('pending','retry')"
        )
        retrying = int(backlog["retrying"] or 0) if backlog else 0
        total = int(backlog["total"] or 0) if backlog else 0
        components["integration"] = {"status": "ok" if retrying == 0 else "retrying", "backlog": total, "retrying": retrying}
        if retrying:
            score -= min(20, 5 + retrying)

        last_maint = self.db.meta("last_intelligence_maintenance")
        maint_age = self._age_minutes(last_maint)
        components["intelligence"] = {"status": "ok" if maint_age is not None and maint_age <= 720 else "stale_or_learning", "age_min": round(maint_age, 1) if maint_age is not None else None}
        if maint_age is not None and maint_age > 720:
            score -= 20

        if run_integrity:
            integrity = self.db.integrity_check()
            components["sqlite"] = {"status": "ok" if integrity == ["ok"] else "error"}
            if integrity != ["ok"]:
                score -= 60

        score = max(0, min(100, score))
        status = "pass" if score >= 90 else "warn" if score >= 70 else "critical"
        previous = self.db.one("SELECT health_score,status FROM operations_snapshots ORDER BY id DESC LIMIT 1")
        self.db.execute(
            "INSERT INTO operations_snapshots(health_score,status,components_json,created_at) VALUES (?,?,?,?)",
            (score, status, json.dumps(components, sort_keys=True), utcnow()),
        )
        self.db.set_meta("last_operations_snapshot", utcnow())
        if self.integration and previous and (previous["status"] != status or abs(int(previous["health_score"] or 0) - score) >= 20):
            self.integration.emit("operations_health_changed", None, {
                "old_status": previous["status"], "new_status": status,
                "old_score": int(previous["health_score"] or 0), "new_score": score,
            })
        return {"health_score": score, "status": status, "components": components}

    def latest(self):
        row = self.db.one("SELECT * FROM operations_snapshots ORDER BY id DESC LIMIT 1")
        if not row:
            return None
        return {
            "health_score": int(row["health_score"] or 0),
            "status": row["status"],
            "components": json.loads(row["components_json"] or "{}"),
            "created_at": row["created_at"],
        }

    def trend(self, limit: int = 24):
        return self.db.all("SELECT health_score,status,created_at FROM operations_snapshots ORDER BY id DESC LIMIT ?", (limit,))
