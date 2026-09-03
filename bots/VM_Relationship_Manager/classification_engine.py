from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from database import Database, utcnow


SAFE_AUTO_TYPES = {"regular", "prospect", "customer", "supplier", "vendor"}
TYPE_ALIASES = {
    "regular": "regular",
    "customer": "customer", "client": "customer", "buyer": "customer",
    "prospect": "prospect", "lead": "prospect",
    "supplier": "supplier", "source": "supplier",
    "vendor": "vendor",
    "partner": "partner",
    "vip": "vip",
    "admin": "admin",
    "group_owner": "group_owner", "group-owner": "group_owner", "owner": "group_owner",
}


@dataclass(frozen=True)
class Evidence:
    points: int
    code: str
    text: str
    inferred_type: str


class ClassificationEngine:
    """Confidence-aware, metadata-first relationship-type inference.

    The engine deliberately abstains when evidence is weak. It never overwrites a
    manual classification lock, and only auto-applies a small safe type set.
    """

    def __init__(self, db: Database, integration=None, calibration=None):
        self.db = db
        self.integration = integration
        self.calibration = calibration

    def _evidence(self, telegram_id: int) -> list[Evidence]:
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not c:
            return []
        out: list[Evidence] = []

        # Explicit structured tags are the strongest non-manual signal.
        for row in self.db.all("SELECT tag FROM tags WHERE telegram_id=?", (telegram_id,)):
            tag = (row["tag"] or "").strip().lower().replace(" ", "_")
            inferred = TYPE_ALIASES.get(tag)
            if inferred:
                out.append(Evidence(98, "explicit_tag", f"Structured tag '{tag}'", inferred))

        # Structured relationship memory is user/admin supplied and therefore
        # stronger than behavioural inference. Only exact recognised terms count.
        for row in self.db.all(
            "SELECT category,memory_key,memory_value FROM relationship_memories WHERE telegram_id=? AND status='active'",
            (telegram_id,),
        ):
            values = [row["category"], row["memory_key"], row["memory_value"]]
            for value in values:
                token = (value or "").strip().lower().replace(" ", "_")
                inferred = TYPE_ALIASES.get(token)
                if inferred:
                    out.append(Evidence(94, "structured_memory", f"Structured memory identifies '{token}'", inferred))
                    break

        # Opportunity state is a high-signal commercial relationship indicator.
        opp = self.db.one(
            """SELECT
                 SUM(CASE WHEN status='won' OR stage='won' THEN 1 ELSE 0 END) won,
                 SUM(CASE WHEN status IN ('open','paused') AND stage IN ('lead','contacted','interested','negotiating','active') THEN 1 ELSE 0 END) active
               FROM opportunities WHERE telegram_id=?""",
            (telegram_id,),
        )
        if opp:
            if int(opp["won"] or 0) > 0:
                out.append(Evidence(92, "won_opportunity", "A recorded opportunity has been won", "customer"))
            elif int(opp["active"] or 0) > 0:
                out.append(Evidence(86, "active_opportunity", "An active commercial opportunity is recorded", "prospect"))

        interactions = int(c["interaction_count"] or 0)
        active_days = int(c["active_days"] or 0)
        score = int(c["relationship_score"] or 0)
        private = self.db.one(
            "SELECT COUNT(*) n FROM private_interactions WHERE telegram_id=?",
            (telegram_id,),
        )
        private_n = int(private["n"] or 0) if private else 0

        # 'regular' is intentionally the only broad behavioural class eligible for
        # automatic inference; higher-status roles require explicit evidence.
        if interactions >= 30 and active_days >= 8 and score >= 60:
            out.append(Evidence(90, "sustained_relationship", "Sustained activity across many days", "regular"))
        elif interactions >= 15 and active_days >= 5 and score >= 45:
            out.append(Evidence(86, "established_activity", "Established repeated activity", "regular"))
        elif private_n >= 12 and active_days >= 4 and score >= 40:
            out.append(Evidence(85, "private_recurrence", "Repeated private interaction pattern", "regular"))

        # VIP is recommendation-only unless explicitly tagged/memorised. This keeps
        # high relationship scores from silently assigning a business-critical role.
        intel = self.db.one("SELECT health_score FROM contact_intelligence WHERE telegram_id=?", (telegram_id,))
        health = int(intel["health_score"] or 0) if intel else 0
        if score >= 85 and health >= 70 and interactions >= 25:
            out.append(Evidence(79, "vip_candidate", "Very strong, healthy, sustained relationship", "vip"))

        return out

    @staticmethod
    def _pick(evidence: Iterable[Evidence]):
        grouped: dict[str, list[Evidence]] = {}
        for e in evidence:
            grouped.setdefault(e.inferred_type, []).append(e)
        if not grouped:
            return "unknown", 0, []
        ranked = []
        for inferred_type, rows in grouped.items():
            rows = sorted(rows, key=lambda x: x.points, reverse=True)
            # Multiple independent signals give a small confidence lift without
            # allowing low-grade evidence to become certain by repetition.
            confidence = min(99, rows[0].points + min(5, max(0, len(rows) - 1) * 2))
            ranked.append((confidence, rows[0].points, inferred_type, rows))
        ranked.sort(reverse=True)
        confidence, _, inferred_type, rows = ranked[0]
        return inferred_type, confidence, rows

    def get(self, telegram_id: int):
        return self.db.one("SELECT * FROM contact_classifications WHERE telegram_id=?", (telegram_id,))

    def set_lock(self, telegram_id: int, locked: bool, admin_id: int | None = None, reason: str = ""):
        current = self.db.one("SELECT relationship_type FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not current:
            return None
        self.db.execute(
            """INSERT INTO contact_classifications
               (telegram_id,predicted_type,confidence,evidence_json,decision_state,auto_applied,
                admin_locked,previous_type,computed_at,reviewed_at,reviewed_by)
               VALUES (?,?,0,'[]','locked',0,?,?,?, ?,?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 admin_locked=excluded.admin_locked,
                 decision_state=CASE WHEN excluded.admin_locked=1 THEN 'locked' ELSE 'suggested' END,
                 reviewed_at=excluded.reviewed_at, reviewed_by=excluded.reviewed_by""",
            (telegram_id, current["relationship_type"], 1 if locked else 0,
             current["relationship_type"], utcnow(), utcnow(), admin_id),
        )
        self.db.execute(
            """INSERT INTO classification_feedback
               (telegram_id,predicted_type,confidence,final_type,outcome,source,details,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (telegram_id, current["relationship_type"], 100, current["relationship_type"],
             "locked" if locked else "unlocked", "admin", reason, utcnow()),
        )
        return self.get(telegram_id)

    def record_manual(self, telegram_id: int, old_type: str, new_type: str, admin_id: int, reason: str = "manual"):
        previous = self.get(telegram_id)
        predicted = previous["predicted_type"] if previous else "unknown"
        confidence = int(previous["confidence"] or 0) if previous else 0
        outcome = "accepted" if predicted == new_type and confidence > 0 else "overridden"
        self.db.execute(
            """INSERT INTO classification_feedback
               (telegram_id,predicted_type,confidence,final_type,outcome,source,details,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (telegram_id, predicted, confidence, new_type, outcome, "admin", reason, utcnow()),
        )
        self.db.execute(
            """INSERT INTO contact_classifications
               (telegram_id,predicted_type,confidence,evidence_json,decision_state,auto_applied,
                admin_locked,previous_type,computed_at,reviewed_at,reviewed_by)
               VALUES (?,?,?,'[]','locked',0,1,?,?,?,?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 admin_locked=1, decision_state='locked', auto_applied=0,
                 previous_type=?, reviewed_at=?, reviewed_by=?""",
            (telegram_id, predicted, confidence, old_type, utcnow(), utcnow(), admin_id,
             old_type, utcnow(), admin_id),
        )
        if self.calibration:
            self.calibration.refresh()

    def compute(self, telegram_id: int, auto_apply: bool = True, threshold: int | None = None):
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not c:
            return None
        ctrl = self.db.one("SELECT * FROM contact_controls WHERE telegram_id=?", (telegram_id,))
        if ctrl and (ctrl["archived"] or ctrl["excluded"]):
            return None

        existing = self.get(telegram_id)
        locked = bool(existing and existing["admin_locked"])
        evidence = self._evidence(telegram_id)
        predicted, confidence, winning = self._pick(evidence)
        evidence_json = json.dumps(
            [{"code": e.code, "points": e.points, "text": e.text, "type": e.inferred_type} for e in sorted(evidence, key=lambda x: x.points, reverse=True)],
            ensure_ascii=False,
        )

        if threshold is None:
            try:
                threshold = int(self.db.meta("classification_auto_threshold", "85"))
            except Exception:
                threshold = 85
        calibrated_enabled = True
        calibrated_threshold = threshold
        if self.calibration and predicted in SAFE_AUTO_TYPES:
            policy = self.calibration.policy_for(predicted)
            calibrated_threshold = max(threshold, int(policy.get("threshold", threshold)))
            calibrated_enabled = bool(policy.get("auto_enabled", True))
        mode = self.db.meta("autonomy_mode", "safe")
        allow_auto = auto_apply and mode == "safe" and not locked and calibrated_enabled
        current_type = c["relationship_type"] or "unknown"
        can_apply = (
            allow_auto
            and current_type == "unknown"
            and predicted in SAFE_AUTO_TYPES
            and confidence >= calibrated_threshold
        )

        was_auto_current = bool(existing and existing["auto_applied"] and current_type == predicted and predicted != "unknown")
        matches_existing = current_type != "unknown" and predicted == current_type
        state = ("locked" if locked else
                 "applied" if (can_apply or was_auto_current) else
                 "confirmed" if matches_existing else
                 "suggested" if predicted != "unknown" else "abstained")
        auto_applied = 1 if was_auto_current else 0
        applied_at = existing["applied_at"] if existing else None
        previous_type = existing["previous_type"] if existing else current_type

        if can_apply:
            previous_type = current_type
            self.db.execute(
                "UPDATE contacts SET relationship_type=?,updated_at=? WHERE telegram_id=?",
                (predicted, utcnow(), telegram_id),
            )
            auto_applied = 1
            applied_at = utcnow()
            self.db.execute(
                """INSERT INTO relationship_events(telegram_id,event_type,details,created_at)
                   VALUES (?,?,?,?)""",
                (telegram_id, "relationship_type_inferred", f"{current_type} -> {predicted} ({confidence}% confidence)", utcnow()),
            )
            self.db.execute(
                """INSERT INTO classification_feedback
                   (telegram_id,predicted_type,confidence,final_type,outcome,source,details,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (telegram_id, predicted, confidence, predicted, "auto_applied", "classifier",
                 winning[0].text if winning else "", utcnow()),
            )
            if self.integration:
                self.integration.emit("classification_changed", telegram_id, {
                    "old_type": current_type, "new_type": predicted,
                    "confidence": confidence, "auto": True,
                })

        self.db.execute(
            """INSERT INTO contact_classifications
               (telegram_id,predicted_type,confidence,evidence_json,decision_state,auto_applied,
                admin_locked,previous_type,computed_at,applied_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 predicted_type=excluded.predicted_type,
                 confidence=excluded.confidence,
                 evidence_json=excluded.evidence_json,
                 decision_state=CASE WHEN contact_classifications.admin_locked=1 THEN 'locked' ELSE excluded.decision_state END,
                 auto_applied=CASE WHEN contact_classifications.admin_locked=1 THEN 0 ELSE excluded.auto_applied END,
                 previous_type=COALESCE(excluded.previous_type,contact_classifications.previous_type),
                 computed_at=excluded.computed_at,
                 applied_at=COALESCE(excluded.applied_at,contact_classifications.applied_at)""",
            (telegram_id, predicted, confidence, evidence_json, state, auto_applied,
             1 if locked else 0, previous_type, utcnow(), applied_at),
        )
        return self.get(telegram_id)

    def apply_prediction(self, telegram_id: int, admin_id: int):
        row = self.compute(telegram_id, auto_apply=False)
        if not row or row["predicted_type"] == "unknown":
            return None
        c = self.db.one("SELECT relationship_type FROM contacts WHERE telegram_id=?", (telegram_id,))
        old = c["relationship_type"]
        new = row["predicted_type"]
        self.db.execute("UPDATE contacts SET relationship_type=?,updated_at=? WHERE telegram_id=?", (new, utcnow(), telegram_id))
        self.db.execute(
            "UPDATE contact_classifications SET decision_state='locked',admin_locked=1,auto_applied=0,previous_type=?,reviewed_at=?,reviewed_by=? WHERE telegram_id=?",
            (old, utcnow(), admin_id, telegram_id),
        )
        self.db.execute(
            """INSERT INTO classification_feedback
               (telegram_id,predicted_type,confidence,final_type,outcome,source,details,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (telegram_id, new, int(row["confidence"] or 0), new, "accepted", "admin", "Applied classifier suggestion", utcnow()),
        )
        if self.calibration:
            self.calibration.refresh()
        if self.integration:
            self.integration.emit("classification_changed", telegram_id, {"old_type": old, "new_type": new, "confidence": row["confidence"], "auto": False})
        return self.get(telegram_id)

    def compute_all(self, auto_apply: bool = True):
        stats = {"computed": 0, "applied": 0, "newly_applied": 0, "suggested": 0, "abstained": 0, "locked": 0, "confirmed": 0}
        for r in self.db.all("SELECT telegram_id FROM contacts"):
            before = self.get(r["telegram_id"])
            was_auto = bool(before and before["auto_applied"])
            row = self.compute(r["telegram_id"], auto_apply=auto_apply)
            if not row:
                continue
            stats["computed"] += 1
            state = row["decision_state"] or "abstained"
            if state in stats:
                stats[state] += 1
            if int(row["auto_applied"] or 0) and not was_auto:
                stats["newly_applied"] += 1
        return stats

    def backlog(self, limit: int = 20):
        return self.db.all(
            """SELECT x.*,c.display_name,c.username,c.relationship_type,c.relationship_score
               FROM contact_classifications x JOIN contacts c ON c.telegram_id=x.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=x.telegram_id
               WHERE x.decision_state='suggested' AND x.predicted_type<>'unknown' AND x.admin_locked=0
                 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY x.confidence DESC,c.relationship_score DESC LIMIT ?""",
            (limit,),
        )

    def stats(self):
        base = self.db.one(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN relationship_type='unknown' THEN 1 ELSE 0 END) unknown
               FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
               WHERE COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0"""
        )
        cls = self.db.one(
            """SELECT COUNT(*) computed,
                      SUM(CASE WHEN decision_state='suggested' THEN 1 ELSE 0 END) suggested,
                      SUM(CASE WHEN auto_applied=1 THEN 1 ELSE 0 END) auto_applied,
                      SUM(CASE WHEN admin_locked=1 THEN 1 ELSE 0 END) locked,
                      ROUND(AVG(CASE WHEN predicted_type<>'unknown' THEN confidence END),1) avg_confidence
               FROM contact_classifications"""
        )
        return {
            "contacts": int(base["total"] or 0), "unknown": int(base["unknown"] or 0),
            "computed": int(cls["computed"] or 0), "suggested": int(cls["suggested"] or 0),
            "auto_applied": int(cls["auto_applied"] or 0), "locked": int(cls["locked"] or 0),
            "avg_confidence": float(cls["avg_confidence"] or 0),
        }
