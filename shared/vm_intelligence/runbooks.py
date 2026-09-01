from __future__ import annotations

from datetime import datetime, timezone
import json

from .v4_schema import ensure_v4_schema


def _now():return datetime.now(timezone.utc).isoformat()

RUNBOOKS={
    "managed_service_offline":{
        "minimum_autonomy":4,
        "steps":["gather_runtime_evidence","check_duplicate_process","attempt_registered_restart","verify_heartbeat","record_outcome"],
        "automatic":True,
        "reversible":True,
    },
    "uncertain_delivery":{
        "minimum_autonomy":2,
        "steps":["freeze_retry","collect_delivery_evidence","request_reconciliation_if_needed"],
        "automatic":False,
        "reversible":True,
    },
    "critical_test_failure":{
        "minimum_autonomy":3,
        "steps":["freeze_release","identify_impacted_suites","prepare_regression_plan","recommend_rollback"],
        "automatic":False,
        "reversible":True,
    },
}


class RunbookEngine:
    def __init__(self,store):self.store=store;ensure_v4_schema(store)
    def catalog(self):return [{"key":k,**v} for k,v in sorted(RUNBOOKS.items())]
    def stats(self):
        with self.store.connect() as con:
            rows=con.execute("SELECT runbook_key,outcome,COUNT(*) n FROM runbook_executions GROUP BY runbook_key,outcome").fetchall()
        out={}
        for r in rows:out.setdefault(r["runbook_key"],{})[r["outcome"]]=int(r["n"])
        return out
    def record(self,key,service,outcome,steps,evidence=None,confidence=None):
        if key not in RUNBOOKS:raise KeyError(key)
        now=_now()
        with self.store.connect() as con:
            con.execute("""INSERT INTO runbook_executions(runbook_key,service,started_at_utc,completed_at_utc,outcome,confidence,steps_json,evidence_json)
                VALUES(?,?,?,?,?,?,?,?)""",(key,service,now,now,outcome,confidence,json.dumps(steps),json.dumps(evidence or {},sort_keys=True,default=str)))
