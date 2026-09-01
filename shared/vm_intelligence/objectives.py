from __future__ import annotations

from datetime import datetime, timezone
import json

from .v4_schema import ensure_v4_schema


def _now():return datetime.now(timezone.utc).isoformat()

DEFAULT_OBJECTIVES=[
    ("healthy_platform","Keep all VM services healthy","Maintain recoverable platform services, verified backups and clean critical tests.",100,4,
     {"critical_incidents_max":0,"managed_services_down_max":0,"backup_integrity_min":1}),
    ("safe_automation","Maximise useful automation safely","Increase autonomous recoveries and useful outcomes without increasing critical incidents or security risk.",85,5,
     {"security_score_min":90,"critical_incidents_max":0}),
    ("minimize_attention","Minimise unnecessary user attention","Reduce noise and manual interventions while preserving meaningful escalation.",75,4,
     {"noise_ratio_max":0.2}),
]


class ObjectiveEngine:
    def __init__(self,store):self.store=store;ensure_v4_schema(store);self.seed()
    def seed(self):
        now=_now()
        with self.store.connect() as con:
            for key,title,desc,priority,ceiling,guardrails in DEFAULT_OBJECTIVES:
                con.execute("""INSERT OR IGNORE INTO operational_objectives(objective_key,title,description,priority,autonomy_ceiling,guardrails_json,created_at_utc,updated_at_utc)
                    VALUES(?,?,?,?,?,?,?,?)""",(key,title,desc,priority,ceiling,json.dumps(guardrails,sort_keys=True),now,now))
    def list(self):
        with self.store.connect() as con:rows=[dict(r) for r in con.execute("SELECT * FROM operational_objectives WHERE enabled=1 ORDER BY priority DESC,objective_key").fetchall()]
        for r in rows:r["guardrails"]=json.loads(r.pop("guardrails_json") or "{}")
        return rows
    def bind_authority(self,results,autonomy,*,backup_available:bool,reliability_freeze:bool=False):
        """Bind every proposed objective step to the registered autonomy policy.

        Unknown actions are fail-closed. This method never executes an action.
        """
        out=[]
        for objective in results:
            row=dict(objective);bound=[]
            for step in objective.get("plan",[]):
                item=dict(step)
                decision=autonomy.explain(
                    item["action"],risk=item.get("risk","low"),
                    backup_available=backup_available,freeze=reliability_freeze,
                )
                item["allowed"]=bool(decision.get("allowed"))
                item["policy_reason"]=decision.get("reason")
                item["explanation"]=decision.get("explanation")
                action=decision.get("action") or {}
                item["minimum_level"]=action.get("minimum_level")
                item["capability"]=action.get("capability")
                bound.append(item)
            row["plan"]=bound
            row["executable_steps"]=sum(1 for x in bound if x.get("allowed"))
            out.append(row)
        return out

    def evaluate(self,context):
        now=_now();results=[]
        for obj in self.list():
            key=obj["objective_key"];guards=obj["guardrails"];violations=[];plan=[]
            if guards.get("critical_incidents_max") is not None and context.get("critical_incidents",0)>guards["critical_incidents_max"]:
                violations.append("critical_incidents")
                plan.append({"priority":100,"action":"gather_diagnostics","risk":"low","reason":"Collect evidence before bounded recovery."})
                plan.append({"priority":97,"action":"restart_unhealthy_process","risk":"low","reason":"Use only for an unhealthy VM-managed process after evidence confirms it."})
            if guards.get("managed_services_down_max") is not None and context.get("managed_services_down",0)>guards["managed_services_down_max"]:
                violations.append("managed_services_down")
                plan.append({"priority":95,"action":"runtime_bridge_recovery","risk":"low","reason":"Recover only a previously validated managed runtime."})
            if guards.get("backup_integrity_min") is not None and (context.get("backup_integrity") or 0)<guards["backup_integrity_min"]:
                violations.append("backup_integrity")
                plan.append({"priority":90,"action":"create_verified_backup","risk":"low","reason":"Create and integrity-check a recovery point before further mutation."})
            if guards.get("security_score_min") is not None and (context.get("security_score") or 0)<guards["security_score_min"]:
                violations.append("security_score")
                plan.append({"priority":92,"action":"enter_safe_mode","risk":"low","reason":"Cap autonomy while security posture is degraded."})
                plan.append({"priority":90,"action":"gather_diagnostics","risk":"low","reason":"Collect secret-safe security evidence."})
            if guards.get("noise_ratio_max") is not None and (context.get("noise_ratio") or 0)>guards["noise_ratio_max"]:
                violations.append("noise_ratio")
                plan.append({"priority":60,"action":"adjust_low_risk_config","risk":"low","reason":"Tune allow-listed notification dedupe only after backup and policy approval."})
            score=max(0.0,100.0-25.0*len(violations));status="healthy" if not violations else "at_risk"
            with self.store.connect() as con:
                con.execute("""INSERT INTO objective_evaluations(objective_key,observed_at_utc,score,status,plan_json,evidence_json)
                    VALUES(?,?,?,?,?,?)""",(key,now,score,status,json.dumps(plan),json.dumps({"violations":violations,"context":context},sort_keys=True,default=str)))
            results.append({"objective_key":key,"title":obj["title"],"priority":obj["priority"],"autonomy_ceiling":obj["autonomy_ceiling"],
                            "score":score,"status":status,"violations":violations,"plan":sorted(plan,key=lambda x:-x["priority"])})
        return results
