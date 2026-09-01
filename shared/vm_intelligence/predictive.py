from __future__ import annotations
from datetime import datetime,timezone,timedelta

# Explainable thresholds. These are operational trigger points, not statistical guarantees.
THRESHOLDS={
    ("Smart_Auto_Poster_V2","failed_24h"):(10.0,"high"),
    ("Smart_Auto_Poster_V2","uncertain_queue"):(1.0,"high"),
    ("Smart_Auto_Poster_V2","account_failure_streaks"):(5.0,"medium"),
    ("VM_Relationship_Manager","health_errors_24h"):(3.0,"medium"),
    ("VM_Relationship_Manager","followups_overdue"):(20.0,"medium"),
    ("VM_Platform","managed_services_down"):(1.0,"critical"),
    ("VM_Platform","open_alerts"):(5.0,"medium"),
}

class PredictiveMaintenance:
    def __init__(self,store):self.store=store

    def _history(self,source,metric,hours=168):
        since=(datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()
        with self.store.connect() as con:
            return [dict(r) for r in con.execute("""SELECT observed_at_utc,value FROM bot_metrics
                WHERE source=? AND metric=? AND observed_at_utc>=? AND value IS NOT NULL
                ORDER BY observed_at_utc""",(source,metric,since)).fetchall()]

    def forecast(self):
        risks=[]
        for (source,metric),(threshold,base_severity) in THRESHOLDS.items():
            hist=self._history(source,metric)
            vals=[float(r["value"]) for r in hist]
            if not vals:continue
            latest=vals[-1]
            deltas=[b-a for a,b in zip(vals,vals[1:])]
            avg_delta=sum(deltas)/len(deltas) if deltas else 0.0
            crossed=latest>=threshold
            if crossed:
                periods=0
            elif avg_delta>0:
                periods=max(1,int((threshold-latest)/avg_delta + .999))
            else:
                periods=None
            if not crossed and (periods is None or periods>6):
                continue
            confidence="high" if len(vals)>=4 and crossed else "medium" if len(vals)>=4 else "low"
            severity=base_severity if crossed else "medium" if periods is not None and periods<=3 else "low"
            risks.append({"source":source,"metric":metric,"latest":round(latest,3),"threshold":threshold,
                          "estimated_periods_to_threshold":periods,"trend_per_period":round(avg_delta,3),
                          "samples":len(vals),"confidence":confidence,"severity":severity,
                          "note":"Simple observed-metric trend; not a causal guarantee."})
        rank={"critical":0,"high":1,"medium":2,"low":3}
        risks.sort(key=lambda x:(rank.get(x["severity"],9),x["estimated_periods_to_threshold"] if x["estimated_periods_to_threshold"] is not None else 999,x["source"],x["metric"]))
        return risks

class PredictiveMaintenanceEngine:
    """Compatibility surface for database-growth forecasting."""
    def __init__(self,metric_store):self.metrics=metric_store
    def growth_forecasts(self):
        targets=[("Smart_Auto_Poster_V2","database_size_mib"),("VM_Relationship_Manager","database_size_mib"),("Universal_Search","legacy_database_size_mib")]
        rows=[]
        for source,metric in targets:
            hist=self.metrics.history(source,metric,hours=24*30,limit=3000);pts=[]
            for r in hist:
                try:
                    t=datetime.fromisoformat(r["observed_at_utc"].replace("Z","+00:00")).timestamp()
                    if r["value"] is not None:pts.append((t,float(r["value"])))
                except Exception:pass
            if len(pts)<2:
                rows.append({"source":source,"metric":metric,"confidence":"insufficient","samples":len(pts)});continue
            first,last=pts[0],pts[-1];days=max((last[0]-first[0])/86400,1/96);per_day=(last[1]-first[1])/days
            rows.append({"source":source,"metric":metric,"samples":len(pts),"current":last[1],
                         "growth_mib_per_day":round(per_day,4),"projected_30d":round(max(0,last[1]+per_day*30),3),
                         "confidence":"medium" if len(pts)>=8 and days>=1 else "low"})
        return rows
