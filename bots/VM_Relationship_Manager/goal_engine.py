from __future__ import annotations

from datetime import datetime, timezone

from database import Database, utcnow

GOAL_TYPES = {"relationship", "commercial", "verification", "followup", "network", "custom"}
GOAL_STATUSES = {"active", "paused", "completed", "cancelled"}


class GoalEngine:
    """Admin-authored relationship objectives with measurable progress.

    Goals are deliberately action metadata; they do not generate or send messages.
    """

    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        telegram_id: int,
        title: str,
        created_by: int | None = None,
        goal_type: str = "relationship",
        priority: int = 50,
        target_at: str | None = None,
        next_step: str | None = None,
    ):
        if not self.db.one("SELECT 1 FROM contacts WHERE telegram_id=?", (telegram_id,)):
            raise ValueError("Contact not found.")
        goal_type = (goal_type or "relationship").strip().lower()
        if goal_type not in GOAL_TYPES:
            raise ValueError(f"Goal type must be one of: {', '.join(sorted(GOAL_TYPES))}")
        title = (title or "").strip()[:180]
        if not title:
            raise ValueError("Goal title is required.")
        priority = max(0, min(100, int(priority)))
        gid = self.db.execute(
            """INSERT INTO relationship_goals
               (telegram_id,goal_type,title,status,priority,target_at,next_step,progress_pct,
                created_by,created_at,updated_at)
               VALUES (?,?,?,'active',?,?,?,?,?,?,?)""",
            (
                telegram_id,
                goal_type,
                title,
                priority,
                target_at,
                (next_step or "").strip()[:300] or None,
                0,
                created_by,
                utcnow(),
                utcnow(),
            ),
        )
        return self.get(gid)

    def get(self, goal_id: int):
        return self.db.one("SELECT * FROM relationship_goals WHERE id=?", (goal_id,))

    def list(self, telegram_id: int | None = None, status: str = "active", limit: int = 50):
        if telegram_id is None:
            return self.db.all(
                """SELECT g.*,c.display_name,c.username FROM relationship_goals g
                   JOIN contacts c ON c.telegram_id=g.telegram_id
                   WHERE g.status=? ORDER BY g.priority DESC,
                     CASE WHEN g.target_at IS NULL THEN 1 ELSE 0 END,g.target_at ASC,g.id DESC LIMIT ?""",
                (status, limit),
            )
        return self.db.all(
            """SELECT * FROM relationship_goals WHERE telegram_id=? AND status=?
               ORDER BY priority DESC,CASE WHEN target_at IS NULL THEN 1 ELSE 0 END,target_at ASC,id DESC LIMIT ?""",
            (telegram_id, status, limit),
        )

    def update(
        self,
        goal_id: int,
        *,
        progress_pct: int | None = None,
        next_step: str | None = None,
        target_at: str | None = None,
        priority: int | None = None,
        status: str | None = None,
    ):
        row = self.get(goal_id)
        if not row:
            raise ValueError("Goal not found.")
        values = {
            "progress_pct": int(row["progress_pct"] or 0),
            "next_step": row["next_step"],
            "target_at": row["target_at"],
            "priority": int(row["priority"] or 50),
            "status": row["status"],
        }
        if progress_pct is not None:
            values["progress_pct"] = max(0, min(100, int(progress_pct)))
        if next_step is not None:
            values["next_step"] = next_step.strip()[:300] or None
        if target_at is not None:
            values["target_at"] = target_at or None
        if priority is not None:
            values["priority"] = max(0, min(100, int(priority)))
        if status is not None:
            status = status.lower().strip()
            if status not in GOAL_STATUSES:
                raise ValueError(f"Goal status must be one of: {', '.join(sorted(GOAL_STATUSES))}")
            values["status"] = status
        completed_at = row["completed_at"]
        if values["status"] == "completed" or values["progress_pct"] >= 100:
            values["status"] = "completed"
            values["progress_pct"] = 100
            completed_at = completed_at or utcnow()
        elif values["status"] == "active":
            completed_at = None
        self.db.execute(
            """UPDATE relationship_goals SET progress_pct=?,next_step=?,target_at=?,priority=?,status=?,
               completed_at=?,updated_at=? WHERE id=?""",
            (
                values["progress_pct"], values["next_step"], values["target_at"], values["priority"],
                values["status"], completed_at, utcnow(), goal_id,
            ),
        )
        return self.get(goal_id)

    def complete(self, goal_id: int):
        return self.update(goal_id, progress_pct=100, status="completed")

    def due(self, limit: int = 30):
        now = utcnow()
        return self.db.all(
            """SELECT g.*,c.display_name,c.username FROM relationship_goals g
               JOIN contacts c ON c.telegram_id=g.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=g.telegram_id
               WHERE g.status='active' AND g.target_at IS NOT NULL AND g.target_at<=?
                 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY g.priority DESC,g.target_at ASC LIMIT ?""",
            (now, limit),
        )

    def stats(self):
        now = utcnow()
        return self.db.one(
            """SELECT COUNT(*) active,
                      SUM(CASE WHEN target_at IS NOT NULL AND target_at<=? THEN 1 ELSE 0 END) overdue,
                      AVG(progress_pct) avg_progress
               FROM relationship_goals WHERE status='active'""",
            (now,),
        )
