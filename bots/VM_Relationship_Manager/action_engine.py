from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database import Database, utcnow


class ActionEngine:
    """Builds a small, deduplicated admin action queue from relationship signals.

    v6 adds fatigue controls: dismissed/done actions enter a cooldown rather than
    being recreated on the next maintenance pass. Repeated persistence is tracked
    via occurrence_count without creating duplicate rows.
    """

    def __init__(self, db: Database, integration=None):
        self.db = db
        self.integration = integration

    @staticmethod
    def _future(value: str | None) -> bool:
        if not value:
            return False
        try:
            return datetime.fromisoformat(value) > datetime.now(timezone.utc)
        except Exception:
            return False

    def _cooldown_days(self, outcome: str) -> int:
        key = "dismissal_cooldown_days" if outcome == "dismissed" else "done_cooldown_days"
        default = "14" if outcome == "dismissed" else "2"
        try:
            return max(0, int(self.db.meta(key, default)))
        except Exception:
            return int(default)

    def _upsert(self, telegram_id: int, action_key: str, title: str, reason: str,
                score: int, confidence: int, source: str, due_at: str | None = None):
        score = max(0, min(100, int(score)))
        confidence = max(0, min(100, int(confidence)))
        now = utcnow()

        existing = self.db.one(
            "SELECT * FROM recommended_actions WHERE telegram_id=? AND action_key=? AND status IN ('open','snoozed') ORDER BY id DESC LIMIT 1",
            (telegram_id, action_key),
        )
        if existing:
            self.db.execute(
                """UPDATE recommended_actions SET title=?,reason=?,action_score=?,confidence=?,source=?,due_at=?,
                       status=CASE WHEN status='snoozed' AND snoozed_until>? THEN 'snoozed' ELSE 'open' END,
                       occurrence_count=COALESCE(occurrence_count,1)+1,last_present_at=?,updated_at=? WHERE id=?""",
                (title, reason, score, confidence, source, due_at, now, now, now, existing["id"]),
            )
            return existing["id"]

        latest = self.db.one(
            "SELECT * FROM recommended_actions WHERE telegram_id=? AND action_key=? ORDER BY id DESC LIMIT 1",
            (telegram_id, action_key),
        )
        if latest and self._future(latest["cooldown_until"]):
            # Deliberate admin feedback wins over automated regeneration.
            return None

        action_id = self.db.execute(
            """INSERT INTO recommended_actions
               (telegram_id,action_key,title,reason,action_score,confidence,source,status,due_at,
                occurrence_count,last_present_at,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,'open',?,1,?,?,?)""",
            (telegram_id, action_key, title, reason, score, confidence, source, due_at, now, now, now),
        )
        if self.integration:
            self.integration.emit("recommended_action_changed", telegram_id, {
                "action_key": action_key, "score": score, "confidence": confidence, "status": "open"
            })
        return action_id

    def _activate(self, active: set[str], telegram_id: int, action_key: str, title: str, reason: str,
                  score: int, confidence: int, source: str, due_at: str | None = None):
        action_id = self._upsert(telegram_id, action_key, title, reason, score, confidence, source, due_at)
        if action_id is not None:
            active.add(action_key)
        return action_id

    def _close_missing(self, telegram_id: int, active_keys: set[str]):
        rows = self.db.all(
            "SELECT id,action_key FROM recommended_actions WHERE telegram_id=? AND status IN ('open','snoozed')",
            (telegram_id,),
        )
        now = utcnow()
        for row in rows:
            if row["action_key"] not in active_keys:
                self.db.execute(
                    "UPDATE recommended_actions SET status='resolved',resolved_at=?,updated_at=? WHERE id=?",
                    (now, now, row["id"]),
                )

    def compute(self, telegram_id: int):
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not c:
            return 0
        ctrl = self.db.one("SELECT * FROM contact_controls WHERE telegram_id=?", (telegram_id,))
        if ctrl and (ctrl["archived"] or ctrl["excluded"]):
            self._close_missing(telegram_id, set())
            return 0

        active: set[str] = set()
        now = utcnow()
        p = self.db.one("SELECT * FROM contact_priorities WHERE telegram_id=?", (telegram_id,))
        cls = self.db.one("SELECT * FROM contact_classifications WHERE telegram_id=?", (telegram_id,))
        f = self.db.one("SELECT * FROM contact_forecasts WHERE telegram_id=?", (telegram_id,))
        i = self.db.one("SELECT * FROM contact_intelligence WHERE telegram_id=?", (telegram_id,))
        b = self.db.one("SELECT * FROM behavior_metrics WHERE telegram_id=?", (telegram_id,))
        q = self.db.one("SELECT * FROM data_quality_metrics WHERE telegram_id=?", (telegram_id,))

        if cls and cls["decision_state"] == "suggested" and int(cls["confidence"] or 0) >= 60:
            self._activate(
                active, telegram_id, "classification_review", f"Classify as {cls['predicted_type']}",
                f"Classifier confidence {cls['confidence']}%; current type is {c['relationship_type']}",
                max(25, min(70, int(cls["confidence"] or 0) - 20)), int(cls["confidence"] or 0), "classification",
            )

        due_followups = self.db.one(
            "SELECT COUNT(*) n,MIN(due_at) due FROM followups WHERE telegram_id=? AND status='open' AND due_at<=?",
            (telegram_id, now),
        )
        if int(due_followups["n"] or 0):
            self._activate(active, telegram_id, "followup_due", "Complete due follow-up",
                           f"{due_followups['n']} follow-up(s) are due", 85, 100, "followup", due_followups["due"])

        goals = self.db.one(
            "SELECT COUNT(*) n,MIN(target_at) due,MAX(priority) maxp FROM relationship_goals WHERE telegram_id=? AND status='active' AND target_at IS NOT NULL AND target_at<=?",
            (telegram_id, now),
        )
        if int(goals["n"] or 0):
            self._activate(active, telegram_id, "goal_due", "Progress overdue relationship goal",
                           f"{goals['n']} goal(s) overdue", min(95, 60 + int(goals["maxp"] or 0)//3), 100, "goal", goals["due"])

        opp = self.db.one(
            "SELECT COUNT(*) n,MIN(due_at) due FROM opportunities WHERE telegram_id=? AND status IN ('open','paused') AND due_at IS NOT NULL AND due_at<=?",
            (telegram_id, now),
        )
        if int(opp["n"] or 0):
            self._activate(active, telegram_id, "opportunity_due", "Progress commercial opportunity",
                           f"{opp['n']} opportunity action(s) overdue", 82, 100, "opportunity", opp["due"])

        risks = self.db.one(
            "SELECT COUNT(*) n,MAX(severity) sev FROM risk_flags WHERE telegram_id=? AND review_status='pending'",
            (telegram_id,),
        )
        if int(risks["n"] or 0):
            self._activate(active, telegram_id, "risk_review", "Review relationship risk signal",
                           f"{risks['n']} pending risk signal(s); max severity {risks['sev']}",
                           min(100, 55 + 9*int(risks["sev"] or 1)), 95, "risk")

        if f and int(f["disengagement_risk"] or 0) >= 60 and int(c["relationship_score"] or 0) >= 45:
            conf = int(f["confidence"] or 0)
            self._activate(active, telegram_id, "reengage", "Review re-engagement",
                           f"Disengagement risk {f['disengagement_risk']}/100; outlook confidence {conf}%",
                           min(85, int(f["reengagement_priority"] or 0)), conf, "forecast")

        if c["verification_status"] in {"unknown", "pending"} and int(c["relationship_score"] or 0) >= 65:
            self._activate(active, telegram_id, "verification_review", "Review verification status",
                           "Strong relationship is not yet verified", 52, 90, "verification")

        if i and i["momentum_label"] in {"growing", "surging"} and int(c["relationship_score"] or 0) >= 55:
            self._activate(active, telegram_id, "reinforce_growth", "Protect positive momentum",
                           f"Relationship momentum is {i['momentum_label']}", 24, 80, "momentum")

        if b and b["behavior_label"] in {"one_sided_ours", "one_sided_theirs"} and int(c["relationship_score"] or 0) >= 55:
            self._activate(active, telegram_id, "reciprocity_review", "Review reciprocity pattern",
                           f"Behaviour pattern is {b['behavior_label']}", 32, 75, "behavior")

        if p and int(p["priority_score"] or 0) >= 50 and not any(k in active for k in {"followup_due","goal_due","opportunity_due","risk_review","reengage"}):
            self._activate(active, telegram_id, "priority_exception", p["next_action"] or "Review relationship",
                           "Relationship priority engine raised an exception", int(p["priority_score"] or 0),
                           int(q["confidence_score"] or 60) if q else 60, "priority")

        self._close_missing(telegram_id, active)
        return len(active)

    def compute_all(self):
        contacts = 0
        actions = 0
        for r in self.db.all("SELECT telegram_id FROM contacts"):
            contacts += 1
            actions += self.compute(r["telegram_id"])
        return {"contacts": contacts, "active_signals": actions}

    def top(self, limit: int = 15, threshold: int | None = None):
        if threshold is None:
            try:
                threshold = int(self.db.meta("exception_threshold", "50"))
            except Exception:
                threshold = 50
        return self.db.all(
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
               ORDER BY a.action_score DESC,a.confidence DESC,c.relationship_score DESC,a.updated_at DESC
               LIMIT ?""",
            (utcnow(), utcnow(), threshold, limit),
        )

    def for_contact(self, telegram_id: int, limit: int = 10):
        self.compute(telegram_id)
        return self.db.all(
            """SELECT * FROM recommended_actions WHERE telegram_id=? AND status IN ('open','snoozed')
               AND (cooldown_until IS NULL OR cooldown_until<=?)
               ORDER BY action_score DESC,confidence DESC LIMIT ?""",
            (telegram_id, utcnow(), limit),
        )

    def _feedback(self, row, outcome: str, details: str = ""):
        self.db.execute(
            """INSERT INTO action_feedback(action_id,telegram_id,action_key,source,outcome,action_score,details,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (row["id"], row["telegram_id"], row["action_key"], row["source"], outcome,
             int(row["action_score"] or 0), details, utcnow()),
        )

    def resolve(self, action_id: int, status: str = "done"):
        if status not in {"done", "dismissed", "resolved"}:
            raise ValueError("Invalid action resolution")
        row = self.db.one("SELECT * FROM recommended_actions WHERE id=?", (action_id,))
        if not row:
            return False
        days = self._cooldown_days("dismissed" if status == "dismissed" else "done")
        cooldown = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat() if days else None
        now = utcnow()
        self.db.execute(
            "UPDATE recommended_actions SET status=?,resolved_at=?,cooldown_until=?,updated_at=? WHERE id=?",
            (status, now, cooldown, now, action_id),
        )
        self._feedback(row, status, f"cooldown_days={days}")
        if self.integration:
            self.integration.emit("recommended_action_changed", row["telegram_id"], {
                "action_key": row["action_key"], "status": status, "action_id": action_id, "cooldown_days": days,
            })
        return True

    def snooze(self, action_id: int, days: int):
        row = self.db.one("SELECT * FROM recommended_actions WHERE id=?", (action_id,))
        if not row:
            return False
        until = (datetime.now(timezone.utc) + timedelta(days=max(0, days))).isoformat()
        self.db.execute(
            "UPDATE recommended_actions SET status='snoozed',snoozed_until=?,updated_at=? WHERE id=?",
            (until, utcnow(), action_id),
        )
        self._feedback(row, "snoozed", f"days={days}")
        return True

    def stats(self):
        row = self.db.one(
            """SELECT COUNT(*) open,
                      SUM(CASE WHEN action_score>=75 THEN 1 ELSE 0 END) critical,
                      SUM(CASE WHEN action_score>=50 THEN 1 ELSE 0 END) exceptions,
                      ROUND(AVG(action_score),1) avg_score
               FROM recommended_actions WHERE status IN ('open','snoozed')
                 AND (cooldown_until IS NULL OR cooldown_until<=?)""",
            (utcnow(),),
        )
        result = {k: (row[k] or 0) for k in row.keys()}
        fb = self.db.one(
            """SELECT SUM(CASE WHEN outcome='dismissed' THEN 1 ELSE 0 END) dismissed,
                      SUM(CASE WHEN outcome='done' THEN 1 ELSE 0 END) done
               FROM action_feedback"""
        )
        result["dismissed"] = int(fb["dismissed"] or 0) if fb else 0
        result["done"] = int(fb["done"] or 0) if fb else 0
        return result
