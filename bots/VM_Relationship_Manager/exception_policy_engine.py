from __future__ import annotations

from database import Database, utcnow


class ExceptionPolicyEngine:
    """Workload-budget policy for admin-by-exception operation.

    Critical items always survive. Normal exceptions are capped and diversified
    across contacts so one relationship cannot consume the entire admin inbox.
    """

    def __init__(self, db: Database):
        self.db = db
        self.ensure_defaults()

    def ensure_defaults(self):
        defaults = {
            "daily_exception_limit": "12",
            "exception_threshold": "50",
            "exception_critical_threshold": "85",
            "exception_per_contact_limit": "2",
            "dismissal_cooldown_days": "14",
            "done_cooldown_days": "2",
        }
        for key, value in defaults.items():
            if self.db.meta(key) is None:
                self.db.set_meta(key, value)

    def settings(self):
        self.ensure_defaults()
        return {
            "limit": max(1, int(self.db.meta("daily_exception_limit", "12"))),
            "threshold": max(0, min(100, int(self.db.meta("exception_threshold", "50")))),
            "critical_threshold": max(50, min(100, int(self.db.meta("exception_critical_threshold", "85")))),
            "per_contact_limit": max(1, int(self.db.meta("exception_per_contact_limit", "2"))),
            "dismissal_cooldown_days": max(1, int(self.db.meta("dismissal_cooldown_days", "14"))),
            "done_cooldown_days": max(0, int(self.db.meta("done_cooldown_days", "2"))),
        }

    def select(self, limit: int | None = None, threshold: int | None = None):
        cfg = self.settings()
        limit = max(1, int(limit if limit is not None else cfg["limit"]))
        threshold = int(threshold if threshold is not None else cfg["threshold"])
        rows = self.db.all(
            """SELECT a.*,c.display_name,c.username,c.relationship_type,c.relationship_score,
                      i.health_score,i.momentum_label
               FROM recommended_actions a JOIN contacts c ON c.telegram_id=a.telegram_id
               LEFT JOIN contact_intelligence i ON i.telegram_id=a.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=a.telegram_id
               WHERE a.status IN ('open','snoozed')
                 AND (a.status='open' OR a.snoozed_until IS NULL OR a.snoozed_until<=?)
                 AND (a.cooldown_until IS NULL OR a.cooldown_until<=?)
                 AND a.action_score>=?
                 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY a.action_score DESC,a.confidence DESC,c.relationship_score DESC,a.updated_at DESC""",
            (utcnow(), utcnow(), threshold),
        )
        critical = [r for r in rows if int(r["action_score"] or 0) >= cfg["critical_threshold"]]
        normal = [r for r in rows if int(r["action_score"] or 0) < cfg["critical_threshold"]]

        selected = []
        per_contact: dict[int, int] = {}

        def take(row, critical_item=False):
            tid = int(row["telegram_id"])
            count = per_contact.get(tid, 0)
            if not critical_item and count >= cfg["per_contact_limit"]:
                return False
            selected.append(row)
            per_contact[tid] = count + 1
            return True

        # Critical work is never hidden by the normal workload budget.
        for row in critical:
            take(row, critical_item=True)

        for row in normal:
            if len(selected) >= max(limit, len(critical)):
                break
            take(row)

        return selected

    def summary(self):
        cfg = self.settings()
        eligible = self.db.one(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN action_score>=? THEN 1 ELSE 0 END) critical
               FROM recommended_actions
               WHERE status IN ('open','snoozed') AND action_score>=?
                 AND (cooldown_until IS NULL OR cooldown_until<=?)""",
            (cfg["critical_threshold"], cfg["threshold"], utcnow()),
        )
        selected = self.select()
        total = int(eligible["total"] or 0) if eligible else 0
        return {
            **cfg,
            "eligible": total,
            "critical": int(eligible["critical"] or 0) if eligible else 0,
            "selected": len(selected),
            "budget_suppressed": max(0, total - len(selected)),
        }
