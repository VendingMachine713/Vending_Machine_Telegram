from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database import Database, utcnow


class GroupEngine:
    """Aggregates the Relationship Manager's known contact/group graph."""
    def __init__(self, db: Database):
        self.db = db

    def compute(self, chat_id: int):
        if int(chat_id) >= 0:
            return None
        title_row = self.db.one(
            "SELECT chat_title FROM contact_groups WHERE chat_id=? AND chat_title IS NOT NULL ORDER BY last_seen DESC LIMIT 1",
            (chat_id,),
        )
        title = title_row["chat_title"] if title_row else str(chat_id)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        contacts = self.db.one("SELECT COUNT(DISTINCT telegram_id) n FROM contact_groups WHERE chat_id=?", (chat_id,))["n"]
        active = self.db.one("SELECT COUNT(DISTINCT telegram_id) n FROM contact_groups WHERE chat_id=? AND last_seen>=?", (chat_id, cutoff))["n"]
        interactions = self.db.one("SELECT COALESCE(SUM(interaction_count),0) n FROM group_daily_activity WHERE chat_id=? AND activity_date>=?", (chat_id, cutoff[:10]))["n"]
        vip = self.db.one(
            """SELECT COUNT(*) n FROM contact_groups g JOIN contacts c ON c.telegram_id=g.telegram_id
               WHERE g.chat_id=? AND c.relationship_type='vip'""", (chat_id,)
        )["n"]
        commercial = self.db.one(
            """SELECT COUNT(*) n FROM contact_groups g JOIN contacts c ON c.telegram_id=g.telegram_id
               WHERE g.chat_id=? AND c.relationship_type IN ('customer','supplier','vendor','partner')""", (chat_id,)
        )["n"]
        avg_score = self.db.one(
            """SELECT COALESCE(AVG(c.relationship_score),0) n FROM contact_groups g JOIN contacts c ON c.telegram_id=g.telegram_id
               WHERE g.chat_id=?""", (chat_id,)
        )["n"]
        bridge = self.db.one(
            """SELECT COUNT(*) n FROM contact_groups g JOIN network_metrics n ON n.telegram_id=g.telegram_id
               WHERE g.chat_id=? AND n.bridge_score>=75""", (chat_id,)
        )["n"]
        value = round(min(100, float(avg_score)*0.45 + min(30, contacts)*1.0 + min(20, commercial*3) + min(15, vip*5) + min(10, bridge*2)))
        self.db.execute(
            """INSERT INTO group_metrics
               (chat_id,chat_title,known_contacts,active_contacts_30,interactions_30,vip_contacts,commercial_contacts,bridge_contacts,avg_relationship_score,group_value_score,computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(chat_id) DO UPDATE SET
                 chat_title=excluded.chat_title,known_contacts=excluded.known_contacts,
                 active_contacts_30=excluded.active_contacts_30,interactions_30=excluded.interactions_30,
                 vip_contacts=excluded.vip_contacts,commercial_contacts=excluded.commercial_contacts,
                 bridge_contacts=excluded.bridge_contacts,avg_relationship_score=excluded.avg_relationship_score,
                 group_value_score=excluded.group_value_score,computed_at=excluded.computed_at""",
            (chat_id,title,contacts,active,int(interactions),vip,commercial,bridge,round(float(avg_score),1),value,utcnow()),
        )
        return self.get(chat_id)

    def get(self, chat_id: int, refresh: bool = False):
        row = self.db.one("SELECT * FROM group_metrics WHERE chat_id=?", (chat_id,))
        if refresh or row is None:
            row = self.compute(chat_id)
        return row

    def compute_all(self):
        ids = [r["chat_id"] for r in self.db.all("SELECT DISTINCT chat_id FROM contact_groups WHERE chat_id<0")]
        for cid in ids:
            self.compute(cid)
        return len(ids)

    def overview(self, limit: int = 30):
        return self.db.all("SELECT * FROM group_metrics ORDER BY group_value_score DESC,active_contacts_30 DESC LIMIT ?", (limit,))

    def top_contacts(self, chat_id: int, limit: int = 15):
        return self.db.all(
            """SELECT c.*,g.interaction_count AS group_interactions,g.last_seen AS group_last_seen,
                      COALESCE(i.health_score,50) health_score
               FROM contact_groups g JOIN contacts c ON c.telegram_id=g.telegram_id
               LEFT JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
               WHERE g.chat_id=? AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY c.relationship_score DESC,g.interaction_count DESC LIMIT ?""",
            (chat_id, limit),
        )
