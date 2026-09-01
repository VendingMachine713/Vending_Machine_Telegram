from __future__ import annotations
from datetime import datetime,timezone
import json

class PostmortemEngine:
    def __init__(self,store):self.store=store

    def refresh(self,incidents,root_causes):
        by_inc={x["incident_id"]:x for x in root_causes};out=[]
        now=datetime.now(timezone.utc).isoformat()
        for inc in incidents:
            if inc["severity"] not in {"critical","high"}:continue
            cause=by_inc.get(inc["incident_id"],{})
            payload={
                "what_happened":inc["title"],
                "when_first_seen":inc["first_seen_utc"],
                "last_seen":inc["last_seen_utc"],
                "occurrences":inc["occurrences"],
                "probable_cause":cause.get("probable_cause"),
                "confidence":cause.get("confidence"),
                "status":inc["status"],
            }
            summary=f"{inc['title']} detected for {inc['source']}."
            impact="Potential service/reliability impact; scope is limited to evidence currently observed."
            recovery="Use the existing bounded VM Core recovery path when the affected service is managed; otherwise preserve state and review evidence."
            prevention="Convert confirmed root cause into a regression test, monitoring rule, or bounded recovery playbook."
            with self.store.connect() as con:
                con.execute("""INSERT INTO postmortems(
                    incident_id,generated_at_utc,status,summary,probable_cause,impact,recovery,prevention,payload_json)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(incident_id) DO UPDATE SET
                      generated_at_utc=excluded.generated_at_utc,status=excluded.status,
                      summary=excluded.summary,probable_cause=excluded.probable_cause,
                      impact=excluded.impact,recovery=excluded.recovery,prevention=excluded.prevention,
                      payload_json=excluded.payload_json""",
                    (inc["incident_id"],now,inc["status"],summary,cause.get("probable_cause"),
                     impact,recovery,prevention,json.dumps(payload,sort_keys=True,default=str)))
            out.append({"incident_id":inc["incident_id"],"source":inc["source"],**payload,
                        "impact":impact,"recovery":recovery,"prevention":prevention})
        return out
