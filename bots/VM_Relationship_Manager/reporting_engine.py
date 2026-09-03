from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from database import Database, utcnow
from exception_policy_engine import ExceptionPolicyEngine


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
        classification = self.db.one("SELECT SUM(CASE WHEN auto_applied=1 THEN 1 ELSE 0 END) auto_applied,SUM(CASE WHEN decision_state='suggested' THEN 1 ELSE 0 END) suggested FROM contact_classifications")
        unknown = self.db.one("SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE c.relationship_type='unknown' AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0")["n"]
        exception_threshold = int(self.db.meta('exception_threshold','50'))
        action_stats = self.db.one("SELECT COUNT(*) open,SUM(CASE WHEN action_score>=? THEN 1 ELSE 0 END) exceptions FROM recommended_actions WHERE status IN ('open','snoozed') AND (cooldown_until IS NULL OR cooldown_until<=?)", (exception_threshold, utcnow()))
        policy = ExceptionPolicyEngine(self.db).summary()
        calibration = self.db.one("SELECT COUNT(*) types,SUM(CASE WHEN auto_enabled=0 THEN 1 ELSE 0 END) quarantined,SUM(sample_count) samples FROM classifier_calibration")
        action_feedback = self.db.one("SELECT SUM(CASE WHEN outcome='done' THEN 1 ELSE 0 END) done,SUM(CASE WHEN outcome='dismissed' THEN 1 ELSE 0 END) dismissed FROM action_feedback WHERE created_at>=?", (since,))
        ops = self.db.one("SELECT health_score,status,created_at FROM operations_snapshots ORDER BY id DESC LIMIT 1")
        payload = {
            "period": period, "days": days, "total_contacts": total, "active_contacts": active,
            "new_contacts": new, "average_health": avg_health, "momentum": dict(momentum),
            "due_followups": due, "open_opportunities": opp, "won_opportunities": won,
            "pending_risk_reviews": risk, "active_goals": int(goals['active'] or 0),
            "overdue_goals": int(goals['overdue'] or 0), "high_disengagement_risk": int(outlook or 0),
            "avg_data_confidence": float(quality['avg_conf'] or 0), "avg_data_completeness": float(quality['avg_complete'] or 0),
            "private_sessions_30": int(sessions or 0), "top_segments": top_segments,
            "autonomy_mode": self.db.meta('autonomy_mode','safe'),
            "unknown_contacts": int(unknown or 0), "auto_classified": int(classification['auto_applied'] or 0),
            "classification_suggestions": int(classification['suggested'] or 0),
            "open_recommended_actions": int(action_stats['open'] or 0), "exception_actions": int(action_stats['exceptions'] or 0),
            "policy_selected_exceptions": int(policy['selected']), "policy_budget_suppressed": int(policy['budget_suppressed']),
            "classifier_feedback_samples": int(calibration['samples'] or 0) if calibration else 0,
            "classifier_quarantined_types": int(calibration['quarantined'] or 0) if calibration else 0,
            "actions_completed_period": int(action_feedback['done'] or 0) if action_feedback else 0,
            "actions_dismissed_period": int(action_feedback['dismissed'] or 0) if action_feedback else 0,
            "operational_health": int(ops['health_score'] or 0) if ops else None,
            "operational_status": ops['status'] if ops else 'learning',
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
