from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json

from .v4_schema import ensure_v4_schema

LEVELS={
    0:"observe",1:"explain",2:"recommend",3:"prepare",4:"recover",5:"experiment",6:"optimize",7:"objective_driven"
}
DEFAULT_ACTIONS=[
    ("gather_diagnostics","Gather diagnostics",0,"low",1,0,0,"diagnostics"),
    ("generate_report","Generate report",0,"low",1,0,0,"reporting"),
    ("prepare_patch","Prepare reversible patch",3,"low",1,1,0,"engineering"),
    ("create_verified_backup","Create and verify a recovery backup",3,"low",1,0,3600,"backup"),
    ("enter_safe_mode","Enter reversible safe mode",4,"low",1,0,0,"governance"),
    ("restart_unhealthy_process","Restart unhealthy managed process",4,"low",1,0,600,"recovery"),
    ("runtime_bridge_recovery","Recover validated runtime bridge service",4,"low",1,0,600,"recovery"),
    ("start_guarded_experiment","Start approved guarded experiment",5,"medium",1,1,0,"experiments"),
    ("adjust_low_risk_config","Adjust allow-listed low-risk config",6,"low",1,1,21600,"optimization"),
]


def _now(): return datetime.now(timezone.utc).isoformat()


class AutonomyController:
    def __init__(self,store):
        self.store=store;ensure_v4_schema(store);self.seed()

    def seed(self):
        now=_now()
        with self.store.connect() as con:
            con.execute("INSERT OR IGNORE INTO autonomy_state(singleton,level,mode,reason,updated_at_utc) VALUES(1,4,'recover','Existing bounded self-healing authority',?)",(now,))
            for row in DEFAULT_ACTIONS:
                con.execute("""INSERT OR IGNORE INTO action_registry(action_key,title,minimum_level,maximum_risk,reversible,requires_backup,cooldown_seconds,capability)
                    VALUES(?,?,?,?,?,?,?,?)""",row)

    def state(self):
        with self.store.connect() as con:
            r=con.execute("SELECT * FROM autonomy_state WHERE singleton=1").fetchone()
        out=dict(r);out["level_name"]=LEVELS.get(out["level"],"unknown")
        return out

    def set_level(self,level:int,reason:str):
        if level not in LEVELS:raise ValueError("level must be 0..7")
        now=_now()
        with self.store.connect() as con:
            con.execute("UPDATE autonomy_state SET level=?,mode=?,reason=?,updated_at_utc=? WHERE singleton=1",(level,LEVELS[level],reason,now))
        return self.state()


    def freeze(self,hours:float=24,reason:str="Safe mode"):
        if hours <= 0:raise ValueError("hours must be positive")
        until=(datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat()
        now=_now()
        with self.store.connect() as con:
            con.execute("UPDATE autonomy_state SET freeze_until_utc=?,reason=?,updated_at_utc=? WHERE singleton=1",(until,reason,now))
        return self.state()

    def unfreeze(self,reason:str="Administrator cleared safe mode"):
        now=_now()
        with self.store.connect() as con:
            con.execute("UPDATE autonomy_state SET freeze_until_utc=NULL,reason=?,updated_at_utc=? WHERE singleton=1",(reason,now))
        return self.state()

    def effective_level(self,reliability_freeze:bool=False):
        st=self.state();level=int(st["level"]);cap=level
        if reliability_freeze or st.get("freeze_until_utc"):
            cap=min(cap,4)
        return {**st,"requested_level":level,"effective_level":cap,"effective_level_name":LEVELS.get(cap,"unknown"),
                "reliability_freeze":bool(reliability_freeze)}

    def explain(self,action_key,risk="low",backup_available=True,freeze=False):
        result=self.allowed(action_key,risk=risk,backup_available=backup_available,freeze=freeze)
        if result.get("allowed"):
            return {**result,"explanation":f"{action_key} is allowed at the current autonomy level and safety boundary."}
        reasons={
            "action_not_registered":"The action is not in the bounded action registry.",
            "reliability_freeze":"Reliability/SLO conditions freeze experiment or optimisation actions.",
            "manual_freeze":"Safe mode is active, so experiment/optimisation actions are frozen.",
            "autonomy_level_too_low":"The configured autonomy level is below this action's minimum level.",
            "backup_required":"The action requires a verified backup before it can run.",
            "risk_exceeds_action_ceiling":"The requested risk exceeds the action's registered ceiling.",
        }
        return {**result,"explanation":reasons.get(result.get("reason"),result.get("reason","blocked"))}

    def allowed(self,action_key,risk="low",backup_available=True,freeze=False):
        st=self.state()
        with self.store.connect() as con:
            row=con.execute("SELECT * FROM action_registry WHERE action_key=? AND enabled=1",(action_key,)).fetchone()
        if not row:return {"allowed":False,"reason":"action_not_registered","state":st}
        if freeze and int(row["minimum_level"])>=5:
            return {"allowed":False,"reason":"reliability_freeze","state":st}
        if st.get("freeze_until_utc") and int(row["minimum_level"])>=5:
            return {"allowed":False,"reason":"manual_freeze","state":st}
        if int(st["level"]) < int(row["minimum_level"]):
            return {"allowed":False,"reason":"autonomy_level_too_low","state":st}
        if row["requires_backup"] and not backup_available:
            return {"allowed":False,"reason":"backup_required","state":st}
        risk_order={"low":1,"medium":2,"high":3,"critical":4}
        if risk_order.get(risk,99)>risk_order.get(str(row["maximum_risk"]),0):
            return {"allowed":False,"reason":"risk_exceeds_action_ceiling","state":st}
        return {"allowed":True,"reason":"registered_bounded_action","state":st,"action":dict(row)}
