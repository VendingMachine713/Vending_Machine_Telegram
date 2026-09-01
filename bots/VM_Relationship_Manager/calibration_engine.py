from __future__ import annotations

from database import Database, utcnow


SAFE_TYPES = ("regular", "prospect", "customer", "supplier", "vendor")


class CalibrationEngine:
    """Conservative feedback calibration for automatic relationship classification.

    Calibration can only make automation *more* conservative than the global
    threshold. Strong admin acceptance keeps the baseline threshold; weak
    acceptance raises it, and repeated disagreement can quarantine a type from
    automatic application while still allowing recommendations.
    """

    def __init__(self, db: Database, integration=None):
        self.db = db
        self.integration = integration

    def _base_threshold(self) -> int:
        try:
            return max(80, min(99, int(self.db.meta("classification_auto_threshold", "85"))))
        except Exception:
            return 85

    def refresh(self):
        base = self._base_threshold()
        rows = []
        for rel_type in SAFE_TYPES:
            agg = self.db.one(
                """SELECT
                       SUM(CASE WHEN outcome='accepted' THEN 1 ELSE 0 END) accepted,
                       SUM(CASE WHEN outcome='overridden' THEN 1 ELSE 0 END) overridden
                   FROM classification_feedback
                   WHERE predicted_type=? AND source='admin' AND outcome IN ('accepted','overridden')""",
                (rel_type,),
            )
            accepted = int((agg["accepted"] if agg else 0) or 0)
            overridden = int((agg["overridden"] if agg else 0) or 0)
            sample = accepted + overridden
            precision = (accepted / sample) if sample else None
            threshold = base
            enabled = 1
            reason = "insufficient feedback; baseline threshold"

            if sample >= 3 and precision is not None:
                if precision >= 0.90:
                    threshold = base
                    reason = "admin feedback supports baseline threshold"
                elif precision >= 0.75:
                    threshold = min(99, base + 3)
                    reason = "mixed admin feedback; threshold raised"
                elif precision >= 0.60:
                    threshold = min(99, base + 7)
                    reason = "weak admin agreement; threshold raised materially"
                else:
                    threshold = 99
                    reason = "poor admin agreement; automatic application restricted"
                    if sample >= 5:
                        enabled = 0
                        reason = "poor repeated admin agreement; auto-application quarantined"

            previous = self.db.one("SELECT effective_threshold,auto_enabled FROM classifier_calibration WHERE relationship_type=?", (rel_type,))
            self.db.execute(
                """INSERT INTO classifier_calibration
                   (relationship_type,sample_count,accepted_count,overridden_count,observed_precision,
                    effective_threshold,auto_enabled,reason,computed_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(relationship_type) DO UPDATE SET
                     sample_count=excluded.sample_count,
                     accepted_count=excluded.accepted_count,
                     overridden_count=excluded.overridden_count,
                     observed_precision=excluded.observed_precision,
                     effective_threshold=excluded.effective_threshold,
                     auto_enabled=excluded.auto_enabled,
                     reason=excluded.reason,
                     computed_at=excluded.computed_at""",
                (rel_type, sample, accepted, overridden, precision, threshold, enabled, reason, utcnow()),
            )
            if self.integration and previous and (int(previous["effective_threshold"] or base) != threshold or bool(previous["auto_enabled"]) != bool(enabled)):
                self.integration.emit("classifier_calibration_changed", None, {
                    "relationship_type": rel_type, "threshold": threshold, "auto_enabled": bool(enabled),
                    "sample_count": sample, "precision": precision,
                })
            rows.append({
                "relationship_type": rel_type,
                "sample_count": sample,
                "accepted": accepted,
                "overridden": overridden,
                "precision": precision,
                "effective_threshold": threshold,
                "auto_enabled": bool(enabled),
                "reason": reason,
            })
        self.db.set_meta("last_classifier_calibration", utcnow())
        return rows

    def policy_for(self, rel_type: str):
        if rel_type not in SAFE_TYPES:
            return {"threshold": 100, "auto_enabled": False, "sample_count": 0, "precision": None}
        row = self.db.one("SELECT * FROM classifier_calibration WHERE relationship_type=?", (rel_type,))
        if not row:
            return {"threshold": self._base_threshold(), "auto_enabled": True, "sample_count": 0, "precision": None}
        return {
            "threshold": int(row["effective_threshold"] or self._base_threshold()),
            "auto_enabled": bool(row["auto_enabled"]),
            "sample_count": int(row["sample_count"] or 0),
            "precision": row["observed_precision"],
            "reason": row["reason"],
        }

    def summary(self):
        rows = self.db.all("SELECT * FROM classifier_calibration ORDER BY relationship_type")
        return {
            "types": len(rows),
            "quarantined": sum(1 for r in rows if not r["auto_enabled"]),
            "feedback_samples": sum(int(r["sample_count"] or 0) for r in rows),
            "rows": rows,
        }
