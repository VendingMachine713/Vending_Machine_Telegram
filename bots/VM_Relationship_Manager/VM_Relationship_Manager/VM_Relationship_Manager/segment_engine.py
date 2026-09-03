from __future__ import annotations

from database import Database, utcnow


class SegmentEngine:
    """Computes dynamic CRM cohorts from existing metadata."""

    def __init__(self, db: Database):
        self.db = db

    def compute(self, telegram_id: int):
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not c:
            return []
        ctrl = self.db.one("SELECT * FROM contact_controls WHERE telegram_id=?", (telegram_id,))
        if ctrl and (ctrl["archived"] or ctrl["excluded"]):
            self.db.execute("DELETE FROM contact_segments WHERE telegram_id=?", (telegram_id,))
            return []
        i = self.db.one("SELECT * FROM contact_intelligence WHERE telegram_id=?", (telegram_id,))
        b = self.db.one("SELECT * FROM behavior_metrics WHERE telegram_id=?", (telegram_id,))
        n = self.db.one("SELECT * FROM network_metrics WHERE telegram_id=?", (telegram_id,))
        p = self.db.one("SELECT * FROM contact_priorities WHERE telegram_id=?", (telegram_id,))
        f = self.db.one("SELECT * FROM contact_forecasts WHERE telegram_id=?", (telegram_id,))
        open_opp = self.db.one(
            "SELECT COUNT(*) n FROM opportunities WHERE telegram_id=? AND status IN ('open','paused')",
            (telegram_id,),
        )["n"]
        due_follow = self.db.one(
            "SELECT COUNT(*) n FROM followups WHERE telegram_id=? AND status='open' AND due_at<=?",
            (telegram_id, utcnow()),
        )["n"]

        segments: list[tuple[str, int, str]] = []
        score = int(c["relationship_score"] or 0)
        health = int(i["health_score"] or 50) if i else 50
        momentum = i["momentum_label"] if i else "learning"
        lifecycle = i["lifecycle_stage"] if i else "learning"
        rel_type = c["relationship_type"]

        def add(key: str, confidence: int, reason: str):
            segments.append((key, max(0, min(100, int(confidence))), reason[:400]))

        if rel_type in {"customer", "supplier", "vendor", "partner"} or open_opp:
            add("commercial", 95 if rel_type != "unknown" else 70, "Commercial relationship or active opportunity")
        if score >= 70:
            add("high_value", min(100, 70 + (score - 70)), f"Relationship score {score}/100")
        if momentum in {"growing", "surging"}:
            add("growing", 85 if momentum == "surging" else 75, f"Momentum {momentum}")
        if health < 50 or momentum in {"cooling", "fading"}:
            add("at_risk", min(95, 60 + max(0, 50 - health)), f"Health {health}/100; momentum {momentum}")
        if n and int(n["bridge_score"] or 0) >= 70:
            add("network_bridge", int(n["bridge_score"]), f"Bridge score {n['bridge_score']}/100")
        if lifecycle in {"new", "developing"} and int(c["interaction_count"] or 0) >= 3:
            add("new_active", 75, f"Lifecycle {lifecycle}; {c['interaction_count']} interactions")
        if lifecycle == "returned" or c["activity_status"] == "returned":
            add("returned", 90, "Previously quiet relationship has returned")
        if c["verification_status"] in {"unknown", "pending"} and score >= 60:
            add("verification_needed", 80, "Strong relationship still unverified")
        if b and b["behavior_label"] in {"one_sided_ours", "one_sided_theirs", "you_initiate", "they_initiate"} and score >= 45:
            add("reciprocity_watch", 70, f"Behaviour pattern {b['behavior_label']}")
        if open_opp:
            add("opportunity_active", min(100, 70 + 5 * int(open_opp)), f"{open_opp} active opportunity/opportunities")
        if due_follow:
            add("followup_due", min(100, 80 + 5 * int(due_follow)), f"{due_follow} follow-up(s) due")
        if p and int(p["priority_score"] or 0) >= 50:
            add("priority_attention", int(p["priority_score"]), f"Priority {p['priority_score']}/100")
        if f and int(f["disengagement_risk"] or 0) >= 60:
            add("disengagement_risk", int(f["disengagement_risk"]), f"Outlook risk {f['disengagement_risk']}/100")

        self.db.execute("DELETE FROM contact_segments WHERE telegram_id=?", (telegram_id,))
        for key, confidence, reason in segments:
            self.db.execute(
                "INSERT INTO contact_segments(telegram_id,segment_key,confidence,reason,computed_at) VALUES (?,?,?,?,?)",
                (telegram_id, key, confidence, reason, utcnow()),
            )
        return self.list_for_contact(telegram_id)

    def list_for_contact(self, telegram_id: int):
        return self.db.all(
            "SELECT * FROM contact_segments WHERE telegram_id=? ORDER BY confidence DESC,segment_key",
            (telegram_id,),
        )

    def compute_all(self):
        count = 0
        for r in self.db.all("SELECT telegram_id FROM contacts"):
            self.compute(r["telegram_id"])
            count += 1
        return count

    def members(self, segment_key: str, limit: int = 30):
        return self.db.all(
            """SELECT s.*,c.display_name,c.username,c.relationship_type,c.relationship_score,
                      i.health_score,i.momentum_label
               FROM contact_segments s JOIN contacts c ON c.telegram_id=s.telegram_id
               LEFT JOIN contact_intelligence i ON i.telegram_id=s.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=s.telegram_id
               WHERE s.segment_key=? AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY s.confidence DESC,c.relationship_score DESC LIMIT ?""",
            (segment_key.strip().lower(), limit),
        )

    def overview(self):
        return self.db.all(
            """SELECT segment_key,COUNT(*) contacts,ROUND(AVG(confidence),1) avg_confidence
               FROM contact_segments GROUP BY segment_key ORDER BY contacts DESC,segment_key"""
        )
