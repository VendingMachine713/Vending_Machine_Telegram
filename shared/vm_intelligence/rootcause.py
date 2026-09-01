from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json

class RootCauseEngine:
    def __init__(self, store):
        self.store=store

    def _derive(self, incident, integrated):
        category=incident["category"]; source=incident["source"]
        evidence=[]
        if category=="managed_service_down":
            return .97,"Managed service process is not alive despite auto-restart policy.",[
                "Runtime snapshot marks at least one managed service down.",
                "The service is within VM Core's managed recovery boundary."
            ]
        if category=="critical_test_failure":
            failed=(json.loads(incident["evidence_json"]) if incident.get("evidence_json") else {}).get("failed_test_suites",[])
            return .98,"A regression or environment mismatch is causing a critical validation suite to fail.",[
                "Critical test status is false.",
                "Failed suites: "+(", ".join(failed) if failed else "not identified")
            ]
        if category=="uncertain_delivery":
            return .93,"Telegram send acknowledgement was uncertain or a send was interrupted.",[
                "SAP intentionally suppresses automatic retry for uncertain sends to avoid duplicate delivery."
            ]
        if category=="account_health_low":
            return .88,"Recent Telegram account failures/cooldowns have reduced SAP account health.",[
                "SAP account health average is below the configured safe operating threshold."
            ]
        if category=="send_success_degraded":
            ev=integrated.get("Smart_Auto_Poster_V2",{}).get("evidence",{})
            kinds=ev.get("top_error_kinds") or []
            if kinds:
                evidence.append("Top queue error kinds: "+", ".join(f"{x['kind']} x{x['count']}" for x in kinds))
            return .78,"Recent SAP queue failures are materially reducing delivery success.",evidence
        if category=="guard_alert":
            try:raw=json.loads(incident.get("evidence_json") or "{}")
            except Exception:raw={}
            detail=raw.get("detail") or "The alert remains open in the VM Core runtime snapshot."
            occurrences=int(raw.get("occurrences") or 0)
            ev=[detail]
            if occurrences:ev.append(f"VM Guard recorded {occurrences} occurrences for this alert key.")
            return (.82 if occurrences>=20 else .72),"VM Guard detected a recurring operational warning/error pattern requiring source-log correlation.",ev
        if category=="component_health_error":
            return .80,"A Relationship Manager supervisor component recorded an error state.",[
                "The bot's own health table contains recent error/offline records."
            ]
        if category=="high_failure_rate":
            return .75,"The action's observed failure ratio is outside its recent operating range.",[
                "Intelligence anomaly detector classified the recent failure rate as abnormal."
            ]
        return .45,"No single cause is established yet; continue evidence collection.",[]

    def refresh(self, incidents, integrated):
        now=datetime.now(timezone.utc).isoformat()
        out=[]
        with self.store.connect() as con:
            for inc in incidents:
                confidence,cause,evidence=self._derive(inc,integrated)
                fp=hashlib.sha256(f"incident:{inc['incident_id']}:{inc['category']}".encode()).hexdigest()[:24]
                payload=json.dumps(evidence,sort_keys=True)
                con.execute("""INSERT INTO root_cause_reports(
                    fingerprint,incident_id,source,created_at_utc,updated_at_utc,confidence,probable_cause,evidence_json)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                      updated_at_utc=excluded.updated_at_utc,
                      confidence=excluded.confidence,
                      probable_cause=excluded.probable_cause,
                      evidence_json=excluded.evidence_json
                """,(fp,inc["incident_id"],inc["source"],now,now,confidence,cause,payload))
                out.append({"incident_id":inc["incident_id"],"source":inc["source"],
                            "confidence":confidence,"probable_cause":cause,"evidence":evidence})
        return out

    def latest(self, source=None, limit=20):
        sql="SELECT * FROM root_cause_reports"
        args=[]
        if source:
            sql+=" WHERE source=?";args.append(source)
        sql+=" ORDER BY updated_at_utc DESC LIMIT ?";args.append(limit)
        with self.store.connect() as con:
            rows=[dict(r) for r in con.execute(sql,args).fetchall()]
        for r in rows:
            try:r["evidence"]=json.loads(r.pop("evidence_json"))
            except Exception:r["evidence"]=[]
        return rows
