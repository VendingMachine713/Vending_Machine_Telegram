from __future__ import annotations

from datetime import datetime, timezone
import json

from .v4_schema import ensure_v4_schema


def _now():return datetime.now(timezone.utc).isoformat()


class ReleaseGate:
    def __init__(self,store):self.store=store;ensure_v4_schema(store)
    def evaluate(self,source,version,baseline_score,candidate_score,critical_incidents,slo_breaches):
        reasons=[]
        delta=None if baseline_score is None or candidate_score is None else round(candidate_score-baseline_score,2)
        if critical_incidents>0:reasons.append("critical_incident_present")
        if slo_breaches>0:reasons.append("slo_breach_present")
        if delta is not None and delta < -3.0:reasons.append("score_regression_gt_3")
        decision="accept" if not reasons else "reject"
        with self.store.connect() as con:
            con.execute("""INSERT INTO release_acceptance(source,version,evaluated_at_utc,baseline_score,candidate_score,score_delta,critical_incidents,slo_breaches,decision,reasons_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",(source,version,_now(),baseline_score,candidate_score,delta,critical_incidents,slo_breaches,decision,json.dumps(reasons)))
        return {"source":source,"version":version,"baseline_score":baseline_score,"candidate_score":candidate_score,
                "score_delta":delta,"critical_incidents":critical_incidents,"slo_breaches":slo_breaches,
                "decision":decision,"reasons":reasons,"automatic_promotion":False}

    def refresh_latest(self,current_score,critical_incidents,slo_breaches):
        with self.store.connect() as con:
            rel=con.execute("SELECT * FROM release_events ORDER BY detected_at_utc DESC LIMIT 1").fetchone()
            if not rel:return None
            existing=con.execute("SELECT * FROM release_acceptance WHERE source=? AND COALESCE(version,'')=COALESCE(?, '') ORDER BY release_id DESC LIMIT 1",
                                 (rel["source"],rel["version"])).fetchone()
        if existing:
            out=dict(existing)
            try:out["reasons"]=json.loads(out.pop("reasons_json"))
            except Exception:out["reasons"]=[]
            return out
        return self.evaluate(rel["source"],rel["version"],rel["baseline_score"],current_score,critical_incidents,slo_breaches)
