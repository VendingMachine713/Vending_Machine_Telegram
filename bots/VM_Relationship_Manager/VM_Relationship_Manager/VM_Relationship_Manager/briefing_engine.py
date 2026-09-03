from __future__ import annotations

from database import Database, utcnow


class BriefingEngine:
    """Produces a concise admin-by-exception operating brief."""

    def __init__(self, db: Database):
        self.db = db

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
        heartbeat = self.db.meta("last_heartbeat")
        return {
            "generated_at": utcnow(),
            "top_priorities": top,
            "overdue_goals": goals,
            "pending_risks": int(risks or 0),
            "unhealthy_opportunities": int(opportunities or 0),
            "high_disengagement_risk": int(high_risk or 0),
            "growing_relationships": int(growing or 0),
            "last_heartbeat": heartbeat,
        }
