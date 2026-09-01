from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json, statistics

from .v42_schema import ensure_v42_schema

def _now_dt():return datetime.now(timezone.utc)
def _now():return _now_dt().isoformat()

def _parse(v):
    try:return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception:return None

SUCCESS_OUTCOMES={"success","succeeded","executed","recovered","ok","passed","win"}
FAIL_OUTCOMES={"failed","failure","error","rolled_back","rollback","loss"}

class ReliabilityEngineering:
    """Historical reliability layer: SLO burn, MTTR/MTBF, recurrence and runbook trust."""
    def __init__(self,store):self.store=store;ensure_v42_schema(store)

    def _incident_stats(self):
        since=(_now_dt()-timedelta(days=30)).isoformat()
        with self.store.connect() as con:
            rows=[dict(r) for r in con.execute(
                "SELECT * FROM incidents WHERE last_seen_utc>=? ORDER BY source,first_seen_utc",(since,)).fetchall()]
        by={}
        for r in rows:
            by.setdefault(r["source"],[]).append(r)
        out={}
        for svc,items in by.items():
            resolved=[x for x in items if x.get("status")=="resolved"]
            durations=[]
            starts=[]
            for x in items:
                a=_parse(x.get("first_seen_utc"));b=_parse(x.get("last_seen_utc"))
                if a:starts.append(a)
                if x.get("status")=="resolved" and a and b and b>=a:
                    durations.append((b-a).total_seconds())
            starts=sorted(starts)
            gaps=[(starts[i]-starts[i-1]).total_seconds() for i in range(1,len(starts))]
            out[svc]={
                "incidents_30d":len(items),
                "recurrences_30d":sum(max(0,int(x.get("occurrences") or 1)-1) for x in items),
                "mttr_seconds":round(statistics.mean(durations),1) if durations else None,
                "mtbf_seconds":round(statistics.mean(gaps),1) if gaps else None,
                "open_incidents":sum(1 for x in items if x.get("status")=="open"),
            }
        return out

    def _runbook_trust(self):
        with self.store.connect() as con:
            rows=[dict(r) for r in con.execute("SELECT * FROM runbook_executions ORDER BY runbook_key,execution_id").fetchall()]
        by={}
        for r in rows:by.setdefault(r["runbook_key"],[]).append(r)
        out={}
        now=_now()
        with self.store.connect() as con:
            for key,items in by.items():
                successes=sum(1 for x in items if str(x.get("outcome","")).lower() in SUCCESS_OUTCOMES)
                failures=sum(1 for x in items if str(x.get("outcome","")).lower() in FAIL_OUTCOMES)
                attempts=len(items);rate=(100.0*successes/attempts) if attempts else None
                durations=[]
                for x in items:
                    a=_parse(x.get("started_at_utc"));b=_parse(x.get("completed_at_utc"))
                    if a and b and b>=a:durations.append((b-a).total_seconds()*1000)
                median=round(statistics.median(durations),1) if durations else None
                evidence=min(1.0,attempts/20.0)
                trust=round((rate or 0.0)*evidence,1)
                cert="certified" if attempts>=20 and (rate or 0)>=95 else "provisional" if attempts>=5 and (rate or 0)>=80 else "unproven"
                row={"runbook_key":key,"attempts":attempts,"successes":successes,"failures":failures,
                     "success_rate_pct":round(rate,1) if rate is not None else None,
                     "median_duration_ms":median,"trust_score":trust,"certification":cert}
                out[key]=row
                con.execute("""INSERT INTO runbook_trust(runbook_key,attempts,successes,failures,success_rate,median_duration_ms,trust_score,certification,updated_at_utc,metadata_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(runbook_key) DO UPDATE SET attempts=excluded.attempts,successes=excluded.successes,
                      failures=excluded.failures,success_rate=excluded.success_rate,median_duration_ms=excluded.median_duration_ms,
                      trust_score=excluded.trust_score,certification=excluded.certification,updated_at_utc=excluded.updated_at_utc""",
                    (key,attempts,successes,failures,rate,median,trust,cert,now,"{}"))
        return out

    def _slo_history(self,current):
        now=_now_dt();history={}
        with self.store.connect() as con:
            defs={r["slo_key"]:dict(r) for r in con.execute("SELECT * FROM slo_definitions WHERE enabled=1").fetchall()}
            for key,d in defs.items():
                since=(now-timedelta(hours=int(d.get("window_hours") or 24))).isoformat()
                rows=[dict(r) for r in con.execute(
                    "SELECT status,error_budget_remaining,observed_at_utc FROM slo_evaluations WHERE slo_key=? AND observed_at_utc>=? ORDER BY observed_at_utc",
                    (key,since)).fetchall()]
                known=[r for r in rows if r["status"]!="unknown"]
                breached=sum(1 for r in known if r["status"]=="breached")
                compliance=100.0*(len(known)-breached)/len(known) if known else None
                allowed_error_pct=float(d.get("error_budget") or 0)
                observed_error_pct=100.0-compliance if compliance is not None else None
                burn=None
                strict_budget=allowed_error_pct<=0
                strict_breach=bool(strict_budget and observed_error_pct is not None and observed_error_pct>0)
                if observed_error_pct is not None and allowed_error_pct>0:
                    burn=observed_error_pct/allowed_error_pct
                elif observed_error_pct==0:
                    burn=0.0
                history[key]={"samples":len(known),"window_hours":d.get("window_hours"),
                              "historical_compliance_pct":round(compliance,1) if compliance is not None else None,
                              "burn_rate":round(burn,2) if burn is not None else None,
                              "strict_zero_budget":strict_budget,
                              "strict_budget_breach":strict_breach}
        enriched=[]
        for row in current.get("slos",[]):
            enriched.append({**row,**history.get(row["slo_key"],{})})
        return enriched

    def evaluate(self,current_reliability,integrated):
        incident=self._incident_stats();trust=self._runbook_trust()
        slos=self._slo_history(current_reliability)
        current_by_service={}
        for x in slos:current_by_service.setdefault(x["service"],[]).append(x)
        services=set(integrated)|set(incident)|set(current_by_service)
        rows=[];now=_now()
        with self.store.connect() as con:
            for svc in sorted(services):
                im=incident.get(svc,{})
                sr=current_by_service.get(svc,[])
                known=[x for x in sr if x.get("status")!="unknown"]
                compliance=100.0*sum(1 for x in known if x.get("status")=="met")/len(known) if known else None
                budgets=[x.get("error_budget_remaining_pct") for x in known if x.get("error_budget_remaining_pct") is not None]
                budget_health=sum(budgets)/len(budgets) if budgets else None
                # Availability is directly known for service runtimes when process_alive exists.
                alive=(integrated.get(svc) or {}).get("metrics",{}).get("process_alive")
                availability=100.0 if alive==1 else 0.0 if alive==0 else None
                related=[v for k,v in trust.items() if svc.lower() in k.lower()]
                runbook_score=max([x["trust_score"] for x in related],default=None)
                row={"service":svc,**im,
                     "availability_pct":availability,
                     "slo_compliance_pct":round(compliance,1) if compliance is not None else None,
                     "error_budget_health_pct":round(budget_health,1) if budget_health is not None else None,
                     "runbook_trust_score":runbook_score}
                rows.append(row)
                con.execute("""INSERT INTO reliability_service_stats(service,incidents_30d,recurrences_30d,mttr_seconds,mtbf_seconds,
                    availability_pct,slo_compliance_pct,error_budget_health_pct,runbook_trust_score,updated_at_utc,metadata_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(service) DO UPDATE SET incidents_30d=excluded.incidents_30d,recurrences_30d=excluded.recurrences_30d,
                      mttr_seconds=excluded.mttr_seconds,mtbf_seconds=excluded.mtbf_seconds,availability_pct=excluded.availability_pct,
                      slo_compliance_pct=excluded.slo_compliance_pct,error_budget_health_pct=excluded.error_budget_health_pct,
                      runbook_trust_score=excluded.runbook_trust_score,updated_at_utc=excluded.updated_at_utc""",
                    (svc,int(im.get("incidents_30d") or 0),int(im.get("recurrences_30d") or 0),im.get("mttr_seconds"),
                     im.get("mtbf_seconds"),availability,row["slo_compliance_pct"],row["error_budget_health_pct"],
                     runbook_score,now,json.dumps({"open_incidents":im.get("open_incidents",0)})))
        numeric_burn=[x["burn_rate"] for x in slos if isinstance(x.get("burn_rate"),(int,float))]
        max_burn=max(numeric_burn,default=0.0)
        strict_breaches=sum(1 for x in slos if x.get("strict_budget_breach"))
        exhausted=sum(1 for x in slos if x.get("status")=="breached" and x.get("error_budget_remaining_pct")==0)
        freeze=bool(current_reliability.get("experiment_freeze_recommended")) or max_burn>2.0 or exhausted>0 or strict_breaches>0
        with self.store.connect() as con:
            con.execute("""INSERT OR REPLACE INTO reliability_windows(window_key,observed_at_utc,compliance_pct,breaches,
                exhausted_budgets,burn_rate_max,payload_json) VALUES(?,?,?,?,?,?,?)""",
                ("current",now,current_reliability.get("compliance_pct"),current_reliability.get("breaches",0),
                 exhausted,max_burn,json.dumps({"slos":slos},sort_keys=True,default=str)))
        return {"slos":slos,"service_stats":rows,"runbook_trust":list(trust.values()),
                "max_burn_rate":round(max_burn,2),"strict_zero_budget_breaches":strict_breaches,
                "error_budgets_exhausted":exhausted,
                "experiment_freeze_recommended":freeze}
