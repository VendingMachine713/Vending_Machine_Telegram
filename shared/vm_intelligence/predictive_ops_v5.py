from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json, math, statistics
from .v5_schema import ensure_v5_schema

def _now_dt():return datetime.now(timezone.utc)
def _now():return _now_dt().isoformat()

class PredictiveOperations:
    def __init__(self,store):self.store=store;ensure_v5_schema(store)

    def _series(self,source,metric,hours=168):
        since=(_now_dt()-timedelta(hours=hours)).isoformat()
        with self.store.connect() as con:
            rows=con.execute("""SELECT observed_at_utc,value FROM bot_metrics
              WHERE source=? AND metric=? AND observed_at_utc>=? ORDER BY observed_at_utc""",
              (source,metric,since)).fetchall()
        return [(r[0],float(r[1])) for r in rows if r[1] is not None]

    @staticmethod
    def _trend(values):
        if len(values)<3:return 0.0
        xs=list(range(len(values)));mx=statistics.mean(xs);my=statistics.mean(values)
        den=sum((x-mx)**2 for x in xs)
        return 0.0 if den==0 else sum((x-mx)*(y-my) for x,y in zip(xs,values))/den

    def forecast(self,integrated):
        rows=[]
        now=_now_dt()
        watch=[
            ("Smart_Auto_Poster_V2","uncertain_queue",24,0.0,"lower"),
            ("Smart_Auto_Poster_V2","pending_queue",24,None,"capacity"),
            ("VM_Platform","managed_services_down",24,0.0,"lower"),
            ("Universal_Search","search_errors",24,0.0,"lower"),
        ]
        for source,metric,horizon,target,mode in watch:
            current=(integrated.get(source) or {}).get("metrics",{}).get(metric)
            hist=self._series(source,metric)
            values=[x[1] for x in hist]
            slope=self._trend(values)
            predicted=(float(current)+slope*max(1,min(horizon,len(values) or 1))) if current is not None else None
            probability=None
            if current is not None:
                volatility=statistics.pstdev(values) if len(values)>=2 else 0.0
                if mode=="lower" and target is not None:
                    risk=max(0.0,float(current)-target)+max(0.0,slope*5)+volatility*.1
                    probability=min(.99,1-math.exp(-risk)) if risk>0 else .03
                elif mode=="capacity":
                    probability=min(.95,.05+max(0,slope)*.1)
            status="watch" if probability is not None and probability>=.35 else "healthy" if probability is not None else "unknown"
            confidence=min(.95,.25+min(20,len(values))*.03)
            due=now+timedelta(hours=horizon)
            row={"source":source,"metric":metric,"horizon_hours":horizon,"current":current,
                 "predicted_value":round(predicted,3) if predicted is not None else None,
                 "probability":round(probability,3) if probability is not None else None,
                 "status":status,"confidence":round(confidence,2),"due_at_utc":due.isoformat()}
            rows.append(row)
            with self.store.connect() as con:
                con.execute("""INSERT INTO predictions(source,metric,horizon_hours,probability,predicted_value,status,
                  confidence,created_at_utc,due_at_utc,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (source,metric,horizon,probability,predicted,status,confidence,_now(),due.isoformat(),
                   json.dumps({"current":current,"slope":slope},sort_keys=True)))
        maintenance=[]
        for r in rows:
            if r["status"]=="watch":
                maintenance.append({"source":r["source"],"action":"inspect_before_failure",
                                    "reason":f"{r['metric']} risk probability {r['probability']}",
                                    "automatic":False,"minimum_level":4})
        return {"predictions":rows,"maintenance":maintenance,"execution_authority":"recommendation_only"}
