from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json

class AutomationOpportunityDetector:
    def __init__(self, store):
        self.store=store

    def _put(self, source, category, title, rationale, confidence, evidence):
        now=datetime.now(timezone.utc).isoformat()
        fp=hashlib.sha256(f"{source}|{category}|{title}".encode()).hexdigest()[:24]
        with self.store.connect() as con:
            con.execute("""INSERT INTO automation_opportunities(
                fingerprint,source,category,title,rationale,confidence,created_at_utc,updated_at_utc,evidence_json)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                  updated_at_utc=excluded.updated_at_utc,
                  rationale=excluded.rationale,
                  confidence=excluded.confidence,
                  evidence_json=excluded.evidence_json
            """,(fp,source,category,title,rationale,confidence,now,now,
                 json.dumps(evidence,sort_keys=True,default=str)))

    def refresh(self, incidents, integrated, technical_debt=None):
        for inc in incidents:
            if int(inc.get("occurrences") or 0)>=3:
                self._put(inc["source"],"recurring_incident",
                    f"Automate recovery for {inc['category'].replace('_',' ')}",
                    "This incident has recurred enough to justify a bounded recovery playbook.",
                    .86,{"incident_id":inc["incident_id"],"occurrences":inc["occurrences"]})
        for alert in integrated.get("VM_Platform",{}).get("evidence",{}).get("open_alerts",[]):
            occurrences=int(alert.get("occurrences") or 0)
            if occurrences>=20:
                self._put(str(alert.get("source") or "VM_Guard"),"alert_calibration",
                    "Review chronic VM Guard alert threshold",
                    f"The same Guard alert has occurred {occurrences} times. Correlate it with actual service impact, then tune the detector if it is noisy rather than actionable.",
                    .84,{"alert_id":alert.get("id"),"occurrences":occurrences,"detail":alert.get("detail")})

        rm=integrated.get("VM_Relationship_Manager",{}).get("evidence",{})
        for row in rm.get("repeated_admin_actions",[]):
            self._put("VM_Relationship_Manager","repeated_admin_action",
                f"Review automation for RM action: {row['action']}",
                f"The same admin action occurred {row['count']} times in the last 24 hours.",
                .75,row)
        td=technical_debt or {}
        if td.get("duplicate_groups"):
            self._put("VM_Core","technical_debt","Consolidate duplicated shared code",
                f"{len(td['duplicate_groups'])} exact duplicate Python groups were detected. Shared VM Core modules may remove repeated maintenance.",
                .82,{"duplicate_groups":len(td["duplicate_groups"])})
        if td.get("large_files"):
            self._put("VM_Core","maintainability","Split oversized modules at stable seams",
                f"{len(td['large_files'])} Python modules exceed the large-file threshold.",
                .70,{"large_files":td["large_files"][:10]})
        return self.open()

    def open(self, limit=50):
        with self.store.connect() as con:
            return [dict(r) for r in con.execute("""SELECT * FROM automation_opportunities
                WHERE status='open' ORDER BY confidence DESC,updated_at_utc DESC LIMIT ?""",(limit,)).fetchall()]
