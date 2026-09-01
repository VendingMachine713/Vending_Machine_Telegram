from __future__ import annotations

from database import Database, utcnow


class BriefingEngine:
    """Produces a concise admin-by-exception operating brief."""

    def __init__(self, db: Database, exception_policy=None):
        self.db = db
        self.exception_policy = exception_policy

    def build(self):
        top = self.db.all(
            """SELECT p.*,c.display_name,c.username,c.relationship_score,i.health_score,i.momentum_label
               FROM contact_priorities p JOIN contacts c ON c.telegram_id=p.telegram_id
               LEFT JOIN contact_intelligence i ON i.telegram_id=p.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=p.telegram_id
               WHERE p.priority_score>0 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
                 AND (p.priority_score>=75 OR p.snoozed_until IS NULL OR p.snoozed_until<=?)
               ORDER BY p.priority_score DESC,c.relationship_score DESC LIMIT 5""",
            (utcnow(),),
        )
        goals = self.db.all(
            """SELECT g.*,c.display_name,c.username FROM relationship_goals g JOIN contacts c ON c.telegram_id=g.telegram_id
               WHERE g.status='active' AND g.target_at IS NOT NULL AND g.target_at<=?
               ORDER BY g.priority DESC,g.target_at ASC LIMIT 5""",
            (utcnow(),),
        )
        risks = self.db.one("SELECT COUNT(*) n FROM risk_flags WHERE review_status='pending'")["n"]
        opportunities = self.db.one(
            "SELECT COUNT(*) n FROM opportunities WHERE status IN ('open','paused') AND health_score<55"
        )["n"]
        high_risk = self.db.one("SELECT COUNT(*) n FROM contact_forecasts WHERE disengagement_risk>=60")["n"]
        growing = self.db.one("SELECT COUNT(*) n FROM contact_intelligence WHERE momentum_label IN ('growing','surging')")["n"]
        unknown = self.db.one("SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE c.relationship_type='unknown' AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0")["n"]
        classification = self.db.one("SELECT SUM(CASE WHEN auto_applied=1 THEN 1 ELSE 0 END) auto_applied,SUM(CASE WHEN decision_state='suggested' THEN 1 ELSE 0 END) suggested FROM contact_classifications")
        exception_threshold = int(self.db.meta('exception_threshold','50'))
        exception_actions = self.db.one("SELECT COUNT(*) n FROM recommended_actions WHERE status IN ('open','snoozed') AND action_score>=? AND (cooldown_until IS NULL OR cooldown_until<=?)", (exception_threshold, utcnow()))["n"]
        policy = self.exception_policy.summary() if self.exception_policy else None
        top_exception_actions = self.exception_policy.select(5) if self.exception_policy else []
        heartbeat = self.db.meta("last_heartbeat")
        return {
            "generated_at": utcnow(),
            "top_priorities": top,
            "overdue_goals": goals,
            "pending_risks": int(risks or 0),
            "unhealthy_opportunities": int(opportunities or 0),
            "high_disengagement_risk": int(high_risk or 0),
            "growing_relationships": int(growing or 0),
            "unknown_contacts": int(unknown or 0),
            "auto_classified": int(classification["auto_applied"] or 0),
            "classification_suggestions": int(classification["suggested"] or 0),
            "exception_actions": int(exception_actions or 0),
            "policy_selected_exceptions": int(policy["selected"] if policy else exception_actions or 0),
            "policy_suppressed_exceptions": int(policy["budget_suppressed"] if policy else 0),
            "top_exception_actions": top_exception_actions,
            "last_heartbeat": heartbeat,
        }
