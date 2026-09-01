from __future__ import annotations
from datetime import datetime, timezone, timedelta
import hashlib, json
from .v5_schema import ensure_v5_schema

def _now(): return datetime.now(timezone.utc).isoformat()
def _parse(v):
    try:return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception:return None

class RootCauseEngine:
    def __init__(self,store):self.store=store;ensure_v5_schema(store)

    def analyze(self,hours=168):
        since=(datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()
        with self.store.connect() as con:
            incidents=[dict(r) for r in con.execute(
                "SELECT * FROM incidents WHERE last_seen_utc>=? ORDER BY first_seen_utc",(since,)).fetchall()]
            events=[dict(r) for r in con.execute(
                "SELECT source,kind,action,outcome,timestamp_utc,metadata_json FROM events WHERE timestamp_utc>=? ORDER BY timestamp_utc",(since,)).fetchall()]
        timelines=[];families={}
        for inc in incidents:
            start=_parse(inc.get("first_seen_utc"));source=inc.get("source")
            nearby=[]
            for ev in events:
                t=_parse(ev.get("timestamp_utc"))
                if not t or not start:continue
                delta=(t-start).total_seconds()
                if -900<=delta<=1800 and (ev.get("source")==source or ev.get("source")=="VM_Platform"):
                    nearby.append({**ev,"delta_seconds":round(delta,1)})
            cat=str(inc.get("category") or "unknown")
            title=str(inc.get("title") or cat)
            family_key=hashlib.sha256(f"{source}|{cat}|{title.lower()[:80]}".encode()).hexdigest()[:20]
            root_candidates=[]
            for ev in nearby:
                score=0.35
                if ev.get("outcome") in {"failure","error","failed"}:score+=0.35
                if ev["delta_seconds"]<=0:score+=0.15
                if str(ev.get("action","")).lower() in {"deploy","update","restart","migrate","config_change"}:score+=0.15
                root_candidates.append({"event":ev,"confidence":round(min(.99,score),2)})
            root_candidates=sorted(root_candidates,key=lambda x:-x["confidence"])[:5]
            family=families.setdefault(family_key,{"family_key":family_key,"title":title,"source":source,
                "incident_count":0,"recurrence_count":0,"root_candidates":[]})
            family["incident_count"]+=1
            family["recurrence_count"]+=max(0,int(inc.get("occurrences") or 1)-1)
            family["root_candidates"].extend(root_candidates[:2])
            timelines.append({"incident_id":inc.get("incident_id"),"source":source,"title":title,
                              "first_seen_utc":inc.get("first_seen_utc"),"events":nearby[:20],
                              "root_candidates":root_candidates})
        now=_now()
        with self.store.connect() as con:
            for f in families.values():
                confidence=max([x["confidence"] for x in f["root_candidates"]],default=.2)
                con.execute("""INSERT INTO failure_families(family_key,title,incident_count,recurrence_count,confidence,root_cause_json,updated_at_utc)
                  VALUES(?,?,?,?,?,?,?) ON CONFLICT(family_key) DO UPDATE SET title=excluded.title,
                  incident_count=excluded.incident_count,recurrence_count=excluded.recurrence_count,
                  confidence=excluded.confidence,root_cause_json=excluded.root_cause_json,updated_at_utc=excluded.updated_at_utc""",
                  (f["family_key"],f["title"],f["incident_count"],f["recurrence_count"],confidence,
                   json.dumps(f["root_candidates"][:5],sort_keys=True,default=str),now))
        return {"timelines":timelines,"failure_families":sorted(families.values(),key=lambda x:(-x["incident_count"],x["title"])),
                "automatic_actions":False}
