from __future__ import annotations

import json
from datetime import datetime, timezone

from database import Database, utcnow


class DataQualityEngine:
    """Scores how much evidence exists behind each contact's intelligence."""

    def __init__(self, db: Database):
        self.db = db

    def compute(self, telegram_id: int):
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not c:
            return None
        b = self.db.one("SELECT * FROM behavior_metrics WHERE telegram_id=?", (telegram_id,))
        n = self.db.one("SELECT * FROM network_metrics WHERE telegram_id=?", (telegram_id,))
        missing = []
        completeness = 25
        active_days = int(c["active_days"] or 0)
        interactions = int(c["interaction_count"] or 0)
        if c["username"] or c["display_name"]:
            completeness += 10
        else:
            missing.append("identity")
        if c["relationship_type"] != "unknown":
            completeness += 10
        else:
            missing.append("classification")
        if c["verification_status"] not in {"unknown", "pending"}:
            completeness += 10
        else:
            missing.append("verification")
        if active_days >= 3:
            completeness += 10
        else:
            missing.append("activity_history")
        if active_days >= 7:
            completeness += 10
        if c["typical_cycle_days"] is not None:
            completeness += 10
        else:
            missing.append("learned_cycle")
        if n and int(n["shared_groups"] or 0) > 0:
            completeness += 5
        if b and int(b["incoming_30"] or 0) + int(b["outgoing_30"] or 0) >= 3:
            completeness += 10
        else:
            missing.append("private_behavior_samples")

        completeness = max(0, min(100, completeness))
        # Confidence is evidence depth, not "truth". Cap early-contact confidence.
        confidence = 20 + min(35, active_days * 3) + min(25, interactions // 4)
        first = datetime.fromisoformat(c["first_seen"])
        age_days = max(0, (datetime.now(timezone.utc) - first).days)
        confidence += min(20, age_days // 7)
        confidence = max(10, min(100, confidence))
        if active_days < 3:
            confidence = min(confidence, 40)
        self.db.execute(
            """INSERT INTO data_quality_metrics
               (telegram_id,completeness_score,confidence_score,missing_fields_json,computed_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 completeness_score=excluded.completeness_score,
                 confidence_score=excluded.confidence_score,
                 missing_fields_json=excluded.missing_fields_json,
                 computed_at=excluded.computed_at""",
            (telegram_id, completeness, confidence, json.dumps(missing), utcnow()),
        )
        return self.get(telegram_id)

    def get(self, telegram_id: int, refresh: bool = False):
        row = self.db.one("SELECT * FROM data_quality_metrics WHERE telegram_id=?", (telegram_id,))
        if refresh or row is None:
            return self.compute(telegram_id)
        return row

    def compute_all(self):
        count = 0
        for r in self.db.all("SELECT telegram_id FROM contacts"):
            self.compute(r["telegram_id"])
            count += 1
        return count

    def low_confidence(self, limit: int = 20):
        return self.db.all(
            """SELECT q.*,c.display_name,c.username,c.relationship_score,c.relationship_type
               FROM data_quality_metrics q JOIN contacts c ON c.telegram_id=q.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=q.telegram_id
               WHERE q.confidence_score<50 AND c.relationship_score>=40
                 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY c.relationship_score DESC,q.confidence_score ASC LIMIT ?""",
            (limit,),
        )
