from __future__ import annotations

import json
from datetime import datetime, timezone

from database import Database, utcnow


class ForecastEngine:
    """Conservative engagement outlook from observed metadata.

    This is an explainable heuristic, not a claim about a person's intentions.
    """

    def __init__(self, db: Database):
        self.db = db

    def compute(self, telegram_id: int):
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not c:
            return None
        i = self.db.one("SELECT * FROM contact_intelligence WHERE telegram_id=?", (telegram_id,))
        b = self.db.one("SELECT * FROM behavior_metrics WHERE telegram_id=?", (telegram_id,))
        s = self.db.one("SELECT * FROM conversation_session_metrics WHERE telegram_id=?", (telegram_id,))
        p = self.db.one("SELECT * FROM contact_priorities WHERE telegram_id=?", (telegram_id,))
        q = self.db.one("SELECT * FROM data_quality_metrics WHERE telegram_id=?", (telegram_id,))

        risk = 20
        reasons: list[dict] = []

        def add(points: int, code: str, text: str):
            nonlocal risk
            risk += points
            reasons.append({"code": code, "points": points, "text": text})

        if i:
            health = int(i["health_score"] or 50)
            overdue = int(i["days_overdue"] or 0)
            momentum = i["momentum_label"]
            if health < 60:
                add(min(30, (60 - health) // 2), "health", f"Health {health}/100")
            if overdue > 0:
                add(min(30, 5 + overdue * 3), "overdue", f"{overdue} day(s) beyond learned cycle")
            if momentum == "cooling":
                add(15, "cooling", "Momentum is cooling")
            elif momentum == "fading":
                add(25, "fading", "Momentum is fading")
            elif momentum in {"growing", "surging"}:
                add(-12, "positive_momentum", f"Momentum is {momentum}")
        if b:
            acc = float(b["acceleration_pct"] or 0)
            if acc <= -50:
                add(15, "activity_drop", f"Recent interaction pace down {abs(round(acc))}%")
            elif acc >= 50:
                add(-8, "activity_growth", f"Recent interaction pace up {round(acc)}%")
            if int(b["reciprocity_score"] or 50) < 35 and int(c["relationship_score"] or 0) >= 45:
                add(8, "reciprocity", "Reciprocity is imbalanced")
        if s and int(s["sessions_30"] or 0) >= 3 and s["session_label"] in {"deep_mutual", "engaged"}:
            add(-8, "session_quality", f"Conversation pattern is {s['session_label']}")
        if c["activity_status"] == "dormant":
            add(25, "dormant", "Contact is dormant")
        if int(c["active_days"] or 0) < 3:
            confidence = 25
        elif int(c["active_days"] or 0) < 7:
            confidence = 45
        elif int(c["active_days"] or 0) < 15:
            confidence = 65
        else:
            confidence = 80
        if q:
            confidence = min(confidence, int(q["confidence_score"] or confidence))

        risk = max(0, min(100, risk))
        if risk >= 75:
            label = "high_risk"
        elif risk >= 55:
            label = "watch"
        elif risk >= 35:
            label = "stable_watch"
        else:
            label = "healthy"
        reengage = max(0, min(100, risk + int(c["relationship_score"] or 0) // 3))
        if p:
            reengage = max(reengage, int(p["priority_score"] or 0))
        reasons.sort(key=lambda x: abs(int(x["points"])), reverse=True)
        self.db.execute(
            """INSERT INTO contact_forecasts
               (telegram_id,disengagement_risk,reengagement_priority,outlook_label,confidence,reason_json,computed_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 disengagement_risk=excluded.disengagement_risk,
                 reengagement_priority=excluded.reengagement_priority,
                 outlook_label=excluded.outlook_label,
                 confidence=excluded.confidence,
                 reason_json=excluded.reason_json,
                 computed_at=excluded.computed_at""",
            (telegram_id, risk, reengage, label, confidence, json.dumps(reasons, ensure_ascii=False), utcnow()),
        )
        return self.get(telegram_id)

    def get(self, telegram_id: int, refresh: bool = False):
        row = self.db.one("SELECT * FROM contact_forecasts WHERE telegram_id=?", (telegram_id,))
        if refresh or row is None:
            return self.compute(telegram_id)
        return row

    def reasons(self, telegram_id: int):
        row = self.get(telegram_id)
        if not row:
            return []
        try:
            return json.loads(row["reason_json"] or "[]")
        except json.JSONDecodeError:
            return []

    def compute_all(self):
        count = 0
        for r in self.db.all("SELECT telegram_id FROM contacts"):
            self.compute(r["telegram_id"])
            count += 1
        return count

    def high_risk(self, limit: int = 20):
        return self.db.all(
            """SELECT f.*,c.display_name,c.username,c.relationship_type,c.relationship_score,i.health_score
               FROM contact_forecasts f JOIN contacts c ON c.telegram_id=f.telegram_id
               LEFT JOIN contact_intelligence i ON i.telegram_id=f.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=f.telegram_id
               WHERE f.disengagement_risk>=55 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY f.reengagement_priority DESC,f.disengagement_risk DESC,c.relationship_score DESC LIMIT ?""",
            (limit,),
        )
