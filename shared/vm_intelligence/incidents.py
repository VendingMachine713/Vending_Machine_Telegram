from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json

def _fp(source, category, key=""):
    raw=json.dumps({"source":source,"category":category,"key":key},sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]

class IncidentEngine:
    def __init__(self, store, analyzer):
        self.store=store; self.analyzer=analyzer

    def _upsert(self, *, fingerprint, source, category, severity, title, evidence):
        now=datetime.now(timezone.utc).isoformat()
        payload=json.dumps(evidence,sort_keys=True,default=str)
        with self.store.connect() as con:
            row=con.execute("SELECT * FROM incidents WHERE fingerprint=?",(fingerprint,)).fetchone()
            if row:
                # Count a recurrence only when evidence meaningfully changes.
                bump = 1 if row["evidence_json"] != payload else 0
                con.execute("""UPDATE incidents SET status='open',last_seen_utc=?,occurrences=occurrences+?,
                    severity=?,title=?,evidence_json=?,resolution='' WHERE fingerprint=?""",
                    (now,bump,severity,title,payload,fingerprint))
                return int(row["incident_id"])
            cur=con.execute("""INSERT INTO incidents(
                fingerprint,source,category,severity,title,first_seen_utc,last_seen_utc,evidence_json)
                VALUES(?,?,?,?,?,?,?,?)""",
                (fingerprint,source,category,severity,title,now,now,payload))
            return int(cur.lastrowid)

    def refresh(self, hours=24, integrated=None):
        active=set()
        for a in self.analyzer.anomalies(hours):
            fp=_fp(a["source"],a["type"],a["action"]); active.add(fp)
            sev="high" if a["type"]=="high_failure_rate" and a.get("failure_rate",0)>=.5 else "medium"
            self._upsert(fingerprint=fp,source=a["source"],category=a["type"],severity=sev,
                title=f"{a['source']}: {a['type'].replace('_',' ')}",evidence=a)

        integrated=integrated or {}
        platform=integrated.get("VM_Platform",{})
        pm=platform.get("metrics",{}); pe=platform.get("evidence",{})
        if pm.get("managed_services_down",0)>0:
            fp=_fp("VM_Platform","managed_service_down");active.add(fp)
            self._upsert(fingerprint=fp,source="VM_Platform",category="managed_service_down",
                severity="critical",title="VM-managed service is down",
                evidence={"count":pm.get("managed_services_down"),"runtime":pe})
        if pm.get("critical_tests_ok") == 0:
            fp=_fp("VM_Platform","critical_test_failure");active.add(fp)
            self._upsert(fingerprint=fp,source="VM_Platform",category="critical_test_failure",
                severity="high",title="Critical platform validation suite is not passing",
                evidence={"failed_test_suites":pe.get("failed_test_suites",[])})
        for alert in pe.get("open_alerts",[]):
            raw=str(alert.get("severity","WARN")).lower()
            sev="high" if raw in {"critical","crit","error","high"} else "medium"
            fp=_fp(str(alert.get("source") or "VM_Guard"),"guard_alert",str(alert.get("id")))
            active.add(fp)
            self._upsert(fingerprint=fp,source=str(alert.get("source") or "VM_Guard"),
                category="guard_alert",severity=sev,title=str(alert.get("title") or "Open VM Guard alert"),
                evidence=alert)

        sap=integrated.get("Smart_Auto_Poster_V2",{})
        sm=sap.get("metrics",{})
        if sm.get("uncertain_queue",0)>0:
            fp=_fp("Smart_Auto_Poster_V2","uncertain_delivery");active.add(fp)
            self._upsert(fingerprint=fp,source="Smart_Auto_Poster_V2",category="uncertain_delivery",
                severity="high",title="SAP has delivery acknowledgements requiring review",
                evidence={"uncertain_queue":sm.get("uncertain_queue"),"details":sap.get("evidence",{})})
        if sm.get("account_health_avg",100)<50:
            fp=_fp("Smart_Auto_Poster_V2","account_health_low");active.add(fp)
            self._upsert(fingerprint=fp,source="Smart_Auto_Poster_V2",category="account_health_low",
                severity="high",title="SAP Telegram account health is low",
                evidence={"account_health_avg":sm.get("account_health_avg")})
        elif sm.get("success_rate_24h",100)<80 and (sm.get("sent_24h",0)+sm.get("failed_24h",0))>=5:
            fp=_fp("Smart_Auto_Poster_V2","send_success_degraded");active.add(fp)
            self._upsert(fingerprint=fp,source="Smart_Auto_Poster_V2",category="send_success_degraded",
                severity="medium",title="SAP send success rate is degraded",
                evidence={"success_rate_24h":sm.get("success_rate_24h"),"details":sap.get("evidence",{})})

        rm=integrated.get("VM_Relationship_Manager",{})
        rm_m=rm.get("metrics",{})
        if rm_m.get("health_errors_24h",0)>0:
            fp=_fp("VM_Relationship_Manager","component_health_error");active.add(fp)
            self._upsert(fingerprint=fp,source="VM_Relationship_Manager",category="component_health_error",
                severity="medium",title="Relationship Manager recorded component health errors",
                evidence={"health_errors_24h":rm_m.get("health_errors_24h"),"details":rm.get("evidence",{})})

        self.store.resolve_absent_incidents(active)
        return self.store.open_incidents()
