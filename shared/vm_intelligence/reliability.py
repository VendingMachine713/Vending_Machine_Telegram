from __future__ import annotations

from datetime import datetime, timezone
import json

from .v4_schema import ensure_v4_schema


def _now():
    return datetime.now(timezone.utc).isoformat()

DEFAULT_SLOS = [
    ("ecosystem_score","VM_Intelligence","overall_score",">=",90.0,24,10.0,"Keep ecosystem score >= 90"),
    ("sap_delivery_success","Smart_Auto_Poster_V2","success_rate_24h",">=",98.0,24,2.0,"SAP delivery success >= 98%"),
    ("sap_uncertain","Smart_Auto_Poster_V2","uncertain_queue","<=",0.0,24,0.0,"SAP unresolved uncertain deliveries = 0"),
    ("admin_available","Admin_Command_Centre","process_alive",">=",1.0,24,0.0,"Admin Command Centre available"),
    ("guard_available","VM_Guard","process_alive",">=",1.0,24,0.0,"VM Guard available"),
    ("platform_managed_down","VM_Platform","managed_services_down","<=",0.0,24,0.0,"Managed services down = 0"),
    ("backup_integrity","VM_Intelligence","latest_backup_integrity",">=",1.0,24,0.0,"Latest backup integrity verified"),
]


class ReliabilityBrain:
    def __init__(self, store):
        self.store = store
        ensure_v4_schema(store)

    def seed(self):
        now = _now()
        with self.store.connect() as con:
            for key,svc,metric,op,target,window,budget,title in DEFAULT_SLOS:
                con.execute(
                    """INSERT OR IGNORE INTO slo_definitions(slo_key,service,metric,operator,target,window_hours,error_budget,title,created_at_utc,updated_at_utc)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (key,svc,metric,op,target,window,budget,title,now,now),
                )

    @staticmethod
    def _met(actual, op, target):
        if actual is None: return None
        if op == ">=": return actual >= target
        if op == "<=": return actual <= target
        if op == ">": return actual > target
        if op == "<": return actual < target
        if op == "==": return actual == target
        return None

    @staticmethod
    def _budget(actual, op, target, budget):
        if actual is None:
            return None
        if budget <= 0:
            return 100.0 if ReliabilityBrain._met(actual,op,target) else 0.0
        if op in (">=", ">"):
            consumed = max(0.0, target - actual)
        elif op in ("<=", "<"):
            consumed = max(0.0, actual - target)
        else:
            consumed = abs(actual-target)
        return round(max(0.0, min(100.0, 100.0 * (1.0 - consumed / budget))), 1)

    def evaluate(self, context):
        self.seed(); now=_now(); rows=[]
        with self.store.connect() as con:
            defs=con.execute("SELECT * FROM slo_definitions WHERE enabled=1 ORDER BY slo_key").fetchall()
            for d in defs:
                actual=(context.get(d["service"]) or {}).get(d["metric"])
                met=self._met(actual,d["operator"],d["target"])
                status="unknown" if met is None else "met" if met else "breached"
                remaining=self._budget(actual,d["operator"],d["target"],float(d["error_budget"] or 0))
                con.execute(
                    """INSERT INTO slo_evaluations(slo_key,observed_at_utc,actual,target,status,error_budget_remaining,details)
                       VALUES(?,?,?,?,?,?,?)""",
                    (d["slo_key"],now,actual,d["target"],status,remaining,d["title"]),
                )
                rows.append({"slo_key":d["slo_key"],"service":d["service"],"metric":d["metric"],
                             "title":d["title"],"actual":actual,"operator":d["operator"],"target":d["target"],
                             "status":status,"error_budget_remaining_pct":remaining})
        breaches=sum(1 for x in rows if x["status"]=="breached")
        known=[x for x in rows if x["status"]!="unknown"]
        compliance=round(100.0*(len(known)-breaches)/len(known),1) if known else 0.0
        freeze=any(x["status"]=="breached" and x["slo_key"] in {"platform_managed_down","backup_integrity"} for x in rows)
        return {"slos":rows,"breaches":breaches,"compliance_pct":compliance,
                "experiment_freeze_recommended":freeze,
                "error_budget_exhausted":[x for x in rows if x["error_budget_remaining_pct"] == 0.0 and x["status"]=="breached"]}
