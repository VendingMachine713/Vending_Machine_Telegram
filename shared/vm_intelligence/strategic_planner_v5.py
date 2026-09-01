from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json
from .v5_schema import ensure_v5_schema

def _now(): return datetime.now(timezone.utc).isoformat()

PRIORITY_ORDER={"P0":0,"P1":1,"P2":2,"P3":3}

class StrategicPlanner:
    """L7 planner. Planning authority is global; execution remains capability-specific."""
    def __init__(self,store):self.store=store;ensure_v5_schema(store)

    def compile(self,snapshot,objectives,capability_trust):
        items=[]
        def add(priority,title,action,authority,impact,risk,confidence,evidence,attention=0,reliability_gain=0,objective=None):
            key=hashlib.sha256(f"{priority}|{title}|{action}".encode()).hexdigest()[:20]
            cap=next((x for x in capability_trust.get("capabilities",[]) if x["capability"]==action),None)
            allowed=bool(cap and cap.get("certification")=="certified" and cap.get("effective_level",0)>=authority)
            item={"backlog_key":key,"priority":priority,"objective_key":objective,"title":title,
                  "impact":impact,"risk":risk,"confidence":confidence,"effort":max(.1,impact/2),
                  "expected_attention_saved":attention,"expected_reliability_gain":reliability_gain,
                  "status":"executable" if allowed else "planned","authority_required":authority,
                  "action_key":action,"allowed":allowed,"evidence":evidence}
            items.append(item)

        rel=snapshot.get("reliability",{})
        hist=rel.get("historical",{})
        if rel.get("breaches",0)>0 or hist.get("error_budgets_exhausted",0)>0:
            add("P0","Recover reliability budget before optimisation","managed_restart",4,10,2,0.98,
                {"breaches":rel.get("breaches"),"burn":hist.get("max_burn_rate")},0,8,"reliability")
        drift=snapshot.get("platform_drift",{})
        if drift.get("counts",{}).get("high",0) or drift.get("counts",{}).get("medium",0):
            add("P1","Resolve high-value platform drift proposals","config_prepare",3,8,3,0.92,
                {"drift_score":drift.get("score"),"findings":len(drift.get("findings",[]))},3,4,"platform_hygiene")
        predictions=snapshot.get("predictive_v5",{}).get("predictions",[])
        risky=[x for x in predictions if (x.get("probability") or 0)>=.35]
        if risky:
            add("P1","Investigate predicted degradation before failure","shadow_runbook_generation",4,8,2,0.88,
                {"predictions":risky[:5]},5,5,"predictive_prevention")
        auto=snapshot.get("automation_discovery_v5",{}).get("candidates",[])
        if auto:
            top=auto[0]
            add("P2",top["title"],"shadow_runbook_generation",4,6,1,top.get("confidence",.7),
                {"candidate":top["candidate_key"]},top.get("estimated_minutes_saved",0),2,"attention")
        eng=snapshot.get("engineering_v5",[])
        if eng:
            add("P2","Advance isolated engineering candidates through release gates","isolated_engineering",4,7,3,.85,
                {"candidates":len(eng)},2,3,"engineering")
        if not items:
            add("P3","Maintain healthy platform and collect more evidence","objective_planning",7,3,1,.99,
                {"score":snapshot.get("scorecard",{}).get("overall")},1,1,"healthy_platform")

        items.sort(key=lambda x:(PRIORITY_ORDER.get(x["priority"],9),-x["impact"],x["title"]))
        now=_now()
        with self.store.connect() as con:
            for x in items:
                con.execute("""INSERT INTO strategic_backlog(backlog_key,priority,objective_key,title,impact,risk,confidence,
                  effort,expected_attention_saved,expected_reliability_gain,status,authority_required,action_key,evidence_json,updated_at_utc)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(backlog_key) DO UPDATE SET priority=excluded.priority,
                  impact=excluded.impact,risk=excluded.risk,confidence=excluded.confidence,effort=excluded.effort,
                  expected_attention_saved=excluded.expected_attention_saved,expected_reliability_gain=excluded.expected_reliability_gain,
                  status=excluded.status,authority_required=excluded.authority_required,action_key=excluded.action_key,
                  evidence_json=excluded.evidence_json,updated_at_utc=excluded.updated_at_utc""",
                  (x["backlog_key"],x["priority"],x["objective_key"],x["title"],x["impact"],x["risk"],x["confidence"],
                   x["effort"],x["expected_attention_saved"],x["expected_reliability_gain"],x["status"],x["authority_required"],
                   x["action_key"],json.dumps(x["evidence"],sort_keys=True,default=str),now))
            executable=sum(1 for x in items if x["allowed"])
            blocked=len(items)-executable
            north_star=float(snapshot.get("attention_budget",{}).get("automatic_decisions",0))+float(snapshot.get("attention_budget",{}).get("estimated_minutes_saved",0))/10.0
            con.execute("""INSERT INTO planner_runs(created_at_utc,objective_count,backlog_count,executable_count,blocked_count,north_star,payload_json)
              VALUES(?,?,?,?,?,?,?)""",(now,len(objectives),len(items),executable,blocked,north_star,json.dumps(items,sort_keys=True,default=str)))
        return {"planner_level":7,"planning_authority":"objective_driven","execution_authority":"capability_specific",
                "backlog":items,"executable_count":sum(1 for x in items if x["allowed"]),
                "blocked_count":sum(1 for x in items if not x["allowed"]),
                "north_star":"useful autonomous outcomes per unit user attention",
                "global_production_execution":False}
