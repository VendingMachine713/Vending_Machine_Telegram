from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib, json
from .v5_schema import ensure_v5_schema

def _now():return datetime.now(timezone.utc).isoformat()

class AutomationDiscovery:
    def __init__(self,store):self.store=store;ensure_v5_schema(store)

    def discover(self,days=30):
        since=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        with self.store.connect() as con:
            decisions=[dict(r) for r in con.execute(
                "SELECT action,outcome,reason,created_at_utc FROM decisions WHERE created_at_utc>=? ORDER BY created_at_utc",(since,)).fetchall()]
        counts=Counter(str(x.get("action") or "unknown") for x in decisions)
        candidates=[];now=_now()
        with self.store.connect() as con:
            for action,freq in counts.items():
                if freq<3:continue
                reversible=1.0 if any(k in action.lower() for k in ("restart","recover","refresh","rotate","inspect")) else .5
                risk="low" if reversible>=.9 else "medium"
                confidence=min(.95,.45+freq*.05)
                minutes=round(freq*2.5,1)
                key=hashlib.sha256(action.encode()).hexdigest()[:20]
                runbook={
                    "trigger":f"repeated:{action}",
                    "preconditions":["target state is verified","action remains reversible"],
                    "diagnostics":["collect current health","collect relevant logs"],
                    "actions":[action],
                    "verification":["health probe passes","no new regression"],
                    "rollback":["restore previous state if verification fails"],
                    "mode":"shadow",
                }
                row={"candidate_key":key,"title":f"Automate repeated {action}","trigger_pattern":action,
                     "frequency":freq,"estimated_minutes_saved":minutes,"reversibility":reversible,
                     "risk":risk,"confidence":round(confidence,2),"status":"shadow","runbook":runbook}
                candidates.append(row)
                con.execute("""INSERT INTO automation_candidates(candidate_key,title,trigger_pattern,frequency,
                  estimated_minutes_saved,reversibility,risk,confidence,status,runbook_json,created_at_utc,updated_at_utc)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(candidate_key) DO UPDATE SET frequency=excluded.frequency,
                  estimated_minutes_saved=excluded.estimated_minutes_saved,reversibility=excluded.reversibility,
                  risk=excluded.risk,confidence=excluded.confidence,status=excluded.status,runbook_json=excluded.runbook_json,
                  updated_at_utc=excluded.updated_at_utc""",
                  (key,row["title"],action,freq,minutes,reversible,risk,confidence,"shadow",
                   json.dumps(runbook,sort_keys=True),now,now))
        return {"candidates":sorted(candidates,key=lambda x:(-x["estimated_minutes_saved"],x["title"])),
                "execution_mode":"shadow","automatic_activation":False}
