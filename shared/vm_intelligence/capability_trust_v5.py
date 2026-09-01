from __future__ import annotations
from datetime import datetime, timezone
import json
from .v5_schema import ensure_v5_schema

def _now():return datetime.now(timezone.utc).isoformat()

DEFAULT_CAPABILITIES={
    "managed_restart":(4,4),
    "log_rotation":(4,4),
    "config_prepare":(3,3),
    "shadow_runbook_generation":(4,4),
    "certified_experiment":(5,5),
    "bounded_optimisation":(6,6),
    "isolated_engineering":(4,4),
    "objective_planning":(7,7),
}
FORBIDDEN={"credential_change","permission_change","irreversible_migration","blind_uncertain_retry","direct_production_source_rewrite"}

class CapabilityTrust:
    def __init__(self,store):self.store=store;ensure_v5_schema(store);self._seed()

    def _seed(self):
        now=_now()
        with self.store.connect() as con:
            for cap,(minimum,maximum) in DEFAULT_CAPABILITIES.items():
                con.execute("""INSERT OR IGNORE INTO capability_trust(capability,minimum_level,maximum_level,
                  attempts,successes,failures,false_positive_actions,rollback_count,trust_score,certification,
                  effective_level,updated_at_utc,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (cap,minimum,maximum,0,0,0,0,0,0,"unproven",min(minimum,4),now,"{}"))

    def record(self,capability,outcome,false_positive=False,rolled_back=False):
        if capability in FORBIDDEN:return
        now=_now()
        with self.store.connect() as con:
            row=con.execute("SELECT * FROM capability_trust WHERE capability=?",(capability,)).fetchone()
            if not row:return
            attempts=row["attempts"]+1
            success=row["successes"]+(1 if outcome in {"success","passed","recovered","win"} else 0)
            failures=row["failures"]+(1 if outcome in {"failed","failure","error","loss"} else 0)
            fp=row["false_positive_actions"]+(1 if false_positive else 0)
            rb=row["rollback_count"]+(1 if rolled_back else 0)
            raw=100.0*success/attempts if attempts else 0.0
            penalty=min(40.0,fp*5+rb*2)
            trust=max(0.0,raw-penalty)
            cert="certified" if attempts>=20 and trust>=95 and fp/max(1,attempts)<=.02 else "provisional" if attempts>=5 and trust>=80 else "unproven"
            effective=int(row["minimum_level"]) if cert=="certified" else min(4,int(row["minimum_level"]))
            con.execute("""UPDATE capability_trust SET attempts=?,successes=?,failures=?,false_positive_actions=?,
              rollback_count=?,trust_score=?,certification=?,effective_level=?,updated_at_utc=? WHERE capability=?""",
              (attempts,success,failures,fp,rb,round(trust,1),cert,effective,now,capability))

    def snapshot(self,requested_level=4):
        with self.store.connect() as con:
            rows=[dict(r) for r in con.execute("SELECT * FROM capability_trust ORDER BY capability").fetchall()]
        for r in rows:
            if r["capability"] in FORBIDDEN:r["effective_level"]=0
            r["allowed_at_requested_level"]=bool(r["certification"]=="certified" and requested_level>=r["minimum_level"])
        return {"requested_level":requested_level,"capabilities":rows,"forbidden":sorted(FORBIDDEN),
                "global_auto_promotion":False}
