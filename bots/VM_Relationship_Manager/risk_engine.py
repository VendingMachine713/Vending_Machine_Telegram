from __future__ import annotations

from database import Database, utcnow


class RiskEngine:
    def __init__(self, db: Database):
        self.db = db

    def pending(self, limit: int = 30):
        return self.db.all(
            """SELECT r.*,c.display_name,c.username,c.trust_score
               FROM risk_flags r JOIN contacts c ON c.telegram_id=r.telegram_id
               WHERE r.review_status='pending' ORDER BY r.severity DESC,r.created_at ASC LIMIT ?""", (limit,)
        )

    def for_contact(self, telegram_id: int, limit: int = 20):
        return self.db.all("SELECT * FROM risk_flags WHERE telegram_id=? ORDER BY id DESC LIMIT ?", (telegram_id, limit))

    def review(self, flag_id: int, status: str, admin_id: int):
        status = status.strip().lower()
        if status not in {"confirmed","dismissed"}:
            raise ValueError("Risk review status must be confirmed or dismissed.")
        flag = self.db.one("SELECT * FROM risk_flags WHERE id=?", (flag_id,))
        if not flag:
            raise ValueError("Risk flag not found.")
        self.db.execute(
            "UPDATE risk_flags SET review_status=?,reviewed_by=?,reviewed_at=? WHERE id=?",
            (status, admin_id, utcnow(), flag_id),
        )
        self.db.execute(
            "INSERT INTO relationship_events(telegram_id,event_type,details,created_at) VALUES (?,?,?,?)",
            (flag["telegram_id"], "risk_reviewed", f"Risk #{flag_id} -> {status}", utcnow()),
        )
        return flag["telegram_id"]
