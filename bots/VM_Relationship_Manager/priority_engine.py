from __future__ import annotations

import json
from datetime import datetime, timezone

from database import Database, utcnow


class PriorityEngine:
    """Ranks relationship work so the admin can manage by exception.

    This is deterministic and metadata-only: no message bodies are inspected.
    """

    def __init__(self, db: Database):
        self.db = db

    def compute(self, telegram_id: int):
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not c:
            return None
        ctrl = self.db.one("SELECT * FROM contact_controls WHERE telegram_id=?", (telegram_id,))
        if ctrl and (ctrl["archived"] or ctrl["excluded"]):
            self.db.execute("DELETE FROM contact_priorities WHERE telegram_id=?", (telegram_id,))
            return None

        intel = self.db.one("SELECT * FROM contact_intelligence WHERE telegram_id=?", (telegram_id,))
        beh = self.db.one("SELECT * FROM behavior_metrics WHERE telegram_id=?", (telegram_id,))
        net = self.db.one("SELECT * FROM network_metrics WHERE telegram_id=?", (telegram_id,))
        now = datetime.now(timezone.utc)
        score = 0
        reasons: list[dict] = []

        rel_score = int(c["relationship_score"] or 0)
        trust = int(c["trust_score"] or 50)
        rel_type = c["relationship_type"]

        def add(points: int, code: str, text: str):
            nonlocal score
            score += points
            reasons.append({"code": code, "points": points, "text": text})

        due_followups = self.db.one(
            "SELECT COUNT(*) n FROM followups WHERE telegram_id=? AND status='open' AND due_at<=?",
            (telegram_id, utcnow()),
        )["n"]
        if due_followups:
            add(min(35, 25 + 5 * (due_followups - 1)), "followup_due", f"{due_followups} follow-up(s) due")

        due_goals = self.db.one(
            "SELECT COUNT(*) n,COALESCE(MAX(priority),0) maxp FROM relationship_goals WHERE telegram_id=? AND status='active' AND target_at IS NOT NULL AND target_at<=?",
            (telegram_id, utcnow()),
        )
        if due_goals["n"]:
            add(min(35, 15 + int(due_goals["n"]) * 5 + int(due_goals["maxp"] or 0) // 10),
                "goal_due", f"{due_goals['n']} relationship goal(s) due")

        opp_due = self.db.one(
            "SELECT COUNT(*) n FROM opportunities WHERE telegram_id=? AND status IN ('open','paused') AND due_at IS NOT NULL AND due_at<=?",
            (telegram_id, utcnow()),
        )["n"]
        if opp_due:
            add(min(30, 20 + 5 * (opp_due - 1)), "opportunity_due", f"{opp_due} opportunity action(s) due")

        pending_risk = self.db.one(
            "SELECT COALESCE(MAX(severity),0) sev, COUNT(*) n FROM risk_flags WHERE telegram_id=? AND review_status='pending'",
            (telegram_id,),
        )
        if pending_risk["n"]:
            add(min(35, 12 + int(pending_risk["sev"]) * 5), "risk_review", f"{pending_risk['n']} risk signal(s) pending review")

        if intel:
            health = int(intel["health_score"] or 50)
            overdue = int(intel["days_overdue"] or 0)
            momentum = intel["momentum_label"]
            if rel_score >= 50 and health < 55:
                add(min(30, 10 + (55 - health) // 2), "health_slipping", f"Relationship health is {health}/100")
            if overdue > 0 and rel_score >= 40:
                add(min(25, 8 + overdue * 2), "cycle_overdue", f"{overdue} day(s) beyond learned cycle")
            if momentum in {"cooling", "fading"} and rel_score >= 40:
                add(12 if momentum == "cooling" else 20, "momentum_down", f"Momentum is {momentum}")
            if momentum in {"growing", "surging"} and rel_score >= 45:
                add(5, "positive_momentum", f"Momentum is {momentum}; consider reinforcing it")

        if c["activity_status"] == "dormant" and (rel_score >= 55 or rel_type in {"vip","supplier","partner","customer"}):
            add(22, "important_dormant", "Important relationship is dormant")

        if rel_type == "unknown" and int(c["interaction_count"] or 0) >= 5:
            add(10, "classification_needed", "Active contact still needs classification")
        if c["verification_status"] in {"unknown", "pending"} and rel_score >= 65:
            add(10, "verification_needed", "Strong relationship is not verified")
        if rel_score >= 80 and rel_type not in {"vip", "partner", "admin"}:
            add(10, "vip_review", "High relationship score suggests VIP review")
        if net and int(net["bridge_score"] or 0) >= 75:
            add(5, "network_bridge", "High-value bridge contact")
        if beh and beh["behavior_label"] in {"one_sided_ours", "one_sided_theirs"} and rel_score >= 50:
            add(5, "reciprocity_review", "Relationship reciprocity is imbalanced")
        forecast = self.db.one("SELECT * FROM contact_forecasts WHERE telegram_id=?", (telegram_id,))
        if forecast and int(forecast["disengagement_risk"] or 0) >= 60 and rel_score >= 45:
            add(min(20, 8 + (int(forecast["disengagement_risk"]) - 60) // 3),
                "disengagement_outlook", f"Disengagement outlook risk {forecast['disengagement_risk']}/100")

        if trust < 35:
            add(15, "low_trust", f"Trust score is {trust}/100")

        score = max(0, min(100, score))
        if score >= 75:
            band = "critical"
        elif score >= 50:
            band = "high"
        elif score >= 25:
            band = "medium"
        elif score > 0:
            band = "low"
        else:
            band = "watch"

        reasons.sort(key=lambda x: x["points"], reverse=True)
        next_action = reasons[0]["text"] if reasons else "No immediate action needed."
        existing = self.db.one("SELECT snoozed_until FROM contact_priorities WHERE telegram_id=?", (telegram_id,))
        snoozed = existing["snoozed_until"] if existing else None
        if score >= 75:
            snoozed = None  # critical work always resurfaces
        self.db.execute(
            """INSERT INTO contact_priorities
               (telegram_id,priority_score,priority_band,reason_json,next_action,snoozed_until,computed_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 priority_score=excluded.priority_score,
                 priority_band=excluded.priority_band,
                 reason_json=excluded.reason_json,
                 next_action=excluded.next_action,
                 snoozed_until=excluded.snoozed_until,
                 computed_at=excluded.computed_at""",
            (telegram_id, score, band, json.dumps(reasons, ensure_ascii=False), next_action, snoozed, utcnow()),
        )
        return self.get(telegram_id)

    def get(self, telegram_id: int, refresh: bool = False):
        row = self.db.one("SELECT * FROM contact_priorities WHERE telegram_id=?", (telegram_id,))
        if refresh or row is None:
            row = self.compute(telegram_id)
        return row

    def refresh_all(self):
        count = 0
        for r in self.db.all("SELECT telegram_id FROM contacts"):
            if self.compute(r["telegram_id"]):
                count += 1
        return count

    def top(self, limit: int = 15):
        return self.db.all(
            """SELECT p.*,c.display_name,c.username,c.relationship_type,c.relationship_score,
                      i.health_score,i.momentum_label
               FROM contact_priorities p
               JOIN contacts c ON c.telegram_id=p.telegram_id
               LEFT JOIN contact_intelligence i ON i.telegram_id=p.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=p.telegram_id
               WHERE COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
                 AND (p.priority_score>=75 OR p.snoozed_until IS NULL OR p.snoozed_until<=?)
               ORDER BY p.priority_score DESC,c.relationship_score DESC,c.last_seen DESC
               LIMIT ?""",
            (utcnow(), limit),
        )

    def snooze(self, telegram_id: int, until_iso: str | None):
        self.compute(telegram_id)
        self.db.execute("UPDATE contact_priorities SET snoozed_until=? WHERE telegram_id=?", (until_iso, telegram_id))
        return self.get(telegram_id)

    def reasons(self, telegram_id: int):
        row = self.get(telegram_id)
        if not row:
            return []
        try:
            return json.loads(row["reason_json"] or "[]")
        except json.JSONDecodeError:
            return []
