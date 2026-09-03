from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from database import Database, utcnow


class ReportingEngine:
    def __init__(self, db: Database):
        self.db = db

    def build(self, period: str = "weekly"):
        period = period.lower()
        days = 30 if period == "monthly" else 7
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        total = self.db.one("SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0")["n"]
        active = self.db.one("SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE c.last_seen>=? AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0", (since,))["n"]
        new = self.db.one("SELECT COUNT(*) n FROM contacts c WHERE c.first_seen>=?", (since,))["n"]
        health_rows = self.db.all("SELECT health_score,momentum_label FROM contact_intelligence")
        avg_health = round(sum(int(r["health_score"]) for r in health_rows)/len(health_rows),1) if health_rows else 0
        momentum = Counter(r["momentum_label"] for r in health_rows)
        due = self.db.one("SELECT COUNT(*) n FROM followups WHERE status='open' AND due_at<=?", (utcnow(),))["n"]
        opp = self.db.one("SELECT COUNT(*) n FROM opportunities WHERE status IN ('open','paused')")["n"]
        won = self.db.one("SELECT COUNT(*) n FROM opportunities WHERE status='won' AND closed_at>=?", (since,))["n"]
        risk = self.db.one("SELECT COUNT(*) n FROM risk_flags WHERE review_status='pending'")["n"]
        goals = self.db.one("SELECT COUNT(*) active,SUM(CASE WHEN target_at IS NOT NULL AND target_at<=? THEN 1 ELSE 0 END) overdue FROM relationship_goals WHERE status='active'", (utcnow(),))
        outlook = self.db.one("SELECT COUNT(*) n FROM contact_forecasts WHERE disengagement_risk>=60")["n"]
        quality = self.db.one("SELECT ROUND(AVG(confidence_score),1) avg_conf,ROUND(AVG(completeness_score),1) avg_complete FROM data_quality_metrics")
        sessions = self.db.one("SELECT COALESCE(SUM(sessions_30),0) n FROM conversation_session_metrics")["n"]
        top_segments = [dict(r) for r in self.db.all("SELECT segment_key,COUNT(*) contacts FROM contact_segments GROUP BY segment_key ORDER BY contacts DESC LIMIT 8")]
        payload = {
            "period": period, "days": days, "total_contacts": total, "active_contacts": active,
            "new_contacts": new, "average_health": avg_health, "momentum": dict(momentum),
            "due_followups": due, "open_opportunities": opp, "won_opportunities": won,
            "pending_risk_reviews": risk, "active_goals": int(goals['active'] or 0),
            "overdue_goals": int(goals['overdue'] or 0), "high_disengagement_risk": int(outlook or 0),
            "avg_data_confidence": float(quality['avg_conf'] or 0), "avg_data_completeness": float(quality['avg_complete'] or 0),
            "private_sessions_30": int(sessions or 0), "top_segments": top_segments,
            "generated_at": utcnow(),
        }
        rid = self.db.execute(
            "INSERT INTO report_snapshots(report_type,period_start,period_end,payload_json,created_at) VALUES (?,?,?,?,?)",
            (period, since, utcnow(), json.dumps(payload, sort_keys=True), utcnow()),
        )
        payload["id"] = rid
        return payload

    def latest(self, period: str = "weekly"):
        row = self.db.one("SELECT * FROM report_snapshots WHERE report_type=? ORDER BY id DESC LIMIT 1", (period,))
        if not row:
            return None
        data = json.loads(row["payload_json"])
        data["id"] = row["id"]
        return data
