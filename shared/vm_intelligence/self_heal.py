from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json, subprocess, sys
from .policy import PolicyEngine
from .lifecycle import effective_policy
from .policy_kernel_v6 import PolicyKernel
from .autonomy import AutonomyController

class SelfHealingController:
    """Only acts inside VM Core's existing managed-service auto-restart boundary."""
    def __init__(self,store,root):
        self.store=store;self.root=Path(root);self.policy=PolicyEngine();self.policy_v6=PolicyKernel(store);self.autonomy_v6=AutonomyController(store)


    def _v6_policy_allows_recovery(self,action_key="managed_restart"):
        # Process liveness in this path is a direct observation. v6 policy is an additional
        # fail-closed gate; it does not replace the historical reversible-action policy.
        security_score=100.0;reliability_freeze=False;backup_ready=False
        try:
            report=json.loads((self.root/"diagnostics"/"intelligence_report.json").read_text(encoding="utf-8-sig"))
            security_score=float((report.get("security") or {}).get("score",100))
            reliability_freeze=bool((report.get("reliability") or {}).get("experiment_freeze_recommended"))
            backup_ready=bool(((report.get("disaster_recovery_v6") or {}).get("latest_backup")) or ((report.get("integrated") or {}).get("VM_Intelligence",{}).get("metrics",{}).get("latest_backup_integrity")))
        except Exception:
            pass
        state=self.autonomy_v6.effective_level(reliability_freeze)
        cap=None
        try:
            with self.store.connect() as con:
                row=con.execute("SELECT * FROM capability_trust WHERE capability='managed_restart'").fetchone()
                cap=dict(row) if row else {"minimum_level":4,"certification":"unproven"}
        except Exception:
            cap={"minimum_level":4,"certification":"unproven"}
        return self.policy_v6.evaluate(action_key=action_key,capability="managed_restart",
            requested_level=int(state.get("requested_level",state.get("level",4))),
            effective_level=int(state.get("effective_level",state.get("level",4))),capability_record=cap,
            risk="low",evidence_quality=100,rollback_ready=True,backup_ready=backup_ready,
            security_score=security_score,reliability_freeze=reliability_freeze,mode="production")

    def _record_interventions(self, action_key, sources, outcome, started_at_utc, completed_at_utc, attention_saved_minutes=2.0):
        immediate=1 if outcome in {"executed","success","recovered"} else 0
        with self.store.connect() as con:
            for source in sources:
                con.execute("""INSERT INTO intervention_outcomes(action_key,source,started_at_utc,completed_at_utc,immediate_success,
                  recurrence_24h,recurrence_7d,root_cause_success,attention_saved_minutes,outcome,evidence_json)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  (action_key,str(source),started_at_utc,completed_at_utc,immediate,None,None,None,
                   float(attention_saved_minutes if immediate else 0),outcome,json.dumps({"controller":"self_heal"},sort_keys=True)))

    def _recent(self, action, minutes=10):
        cutoff=(datetime.now(timezone.utc)-timedelta(minutes=minutes)).isoformat()
        with self.store.connect() as con:
            return con.execute("SELECT 1 FROM decisions WHERE action=? AND created_at_utc>=? LIMIT 1",
                               (action,cutoff)).fetchone() is not None

    def _bridge_recovery(self):
        state_path=self.root/"state"/"runtime_bridge.json"
        status_path=self.root/"diagnostics"/"runtime_bridge_status.json"
        if not state_path.is_file():
            return []
        try:
            state=json.loads(state_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return []
        try:
            status=json.loads(status_path.read_text(encoding="utf-8-sig")) if status_path.is_file() else {}
        except Exception:
            status={}
        status_by={str(x.get("bot")):x for x in status.get("services",[]) if x.get("bot")}
        desired=[x for x in state.get("services",[]) if x.get("desired_running")]
        down=[x for x in desired if not ((status_by.get(str(x.get("bot"))) or {}).get("status") or {}).get("alive")]
        if not down or self._recent("runtime_bridge_recovery"):
            return []
        decision=self.policy.decide("restart_unhealthy_process",reversible=True,risk="low",confidence=.98)
        if decision.authority!="automatic":
            return []
        v6=self._v6_policy_allows_recovery("managed_restart")
        if v6["decision"]!="ALLOW":
            self.store.record_decision(source="VM_Intelligence",action="runtime_bridge_recovery",authority="blocked",risk="low",confidence=.98,
                reason="v6 policy kernel: "+",".join(v6["reasons"]),outcome="deferred",metadata={"policy":v6})
            return []
        tool=self.root/"tools"/"Intelligence"/"RUNTIME_BRIDGE.py"
        if not tool.is_file():
            return []
        report=self.root/"diagnostics"/"runtime_bridge_status.json"
        started_at=datetime.now(timezone.utc).isoformat()
        try:
            proc=subprocess.run([sys.executable,str(tool),"--root",str(self.root),"--mode","ensure",
                                 "--report",str(report)],cwd=self.root,capture_output=True,text=True,timeout=45)
            outcome="executed" if proc.returncode==0 else "failed"
            result={"returncode":proc.returncode,"stdout":proc.stdout[-2000:],"stderr":proc.stderr[-2000:]}
        except Exception as exc:
            outcome="failed";result={"error":type(exc).__name__}
        completed_at=datetime.now(timezone.utc).isoformat()
        self._record_interventions("managed_restart",[x.get("bot") for x in down],outcome,started_at,completed_at,3.0)
        self.store.record_decision(source="VM_Intelligence",action="runtime_bridge_recovery",
            authority="automatic",risk="low",confidence=.98,
            reason="Recover previously validated managed service through reversible runtime bridge.",
            outcome=outcome,metadata={"down":[x.get("bot") for x in down],"result":result})
        return [{"action":"runtime_bridge_recovery","down":[x.get("bot") for x in down],
                 "outcome":outcome,"result":result}]

    def run(self):
        actions=self._bridge_recovery()
        path=self.root/"diagnostics"/"live_runtime.json"
        try:data=json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:return actions
        bridge_state={}
        try:
            b=json.loads((self.root/"state"/"runtime_bridge.json").read_text(encoding="utf-8-sig"))
            bridge_state={str(x.get("bot")) for x in b.get("services",[]) if x.get("desired_running")}
        except Exception:
            bridge_state=set()
        down=[]
        for row in data.get("services",[]):
            name=row.get("name")
            policy=effective_policy(self.root,str(name)) if name else {}
            if policy.get("auto_restart") and not row.get("process_alive") and str(name) not in bridge_state:
                down.append(row)
        if not down:return actions
        if self._recent("restart_unhealthy_process"):return actions
        decision=self.policy.decide("restart_unhealthy_process",reversible=True,risk="low",confidence=.98)
        if decision.authority!="automatic":
            self.store.record_decision(source="VM_Intelligence",action=decision.action,
                authority=decision.authority,risk="low",confidence=.98,reason=decision.reason,
                metadata={"down":[x.get("name") for x in down]})
            return actions
        v6=self._v6_policy_allows_recovery("managed_restart")
        if v6["decision"]!="ALLOW":
            self.store.record_decision(source="VM_Intelligence",action=decision.action,authority="blocked",risk="low",confidence=.98,
                reason="v6 policy kernel: "+",".join(v6["reasons"]),outcome="deferred",metadata={"down":[x.get("name") for x in down],"policy":v6})
            return actions
        started_at=datetime.now(timezone.utc).isoformat()
        try:
            from shared.vm_core.supervisor import supervise_once
            result=supervise_once(self.root,apply=True)
            outcome="executed"
        except Exception as exc:
            result={"error":type(exc).__name__};outcome="failed"
        completed_at=datetime.now(timezone.utc).isoformat()
        self._record_interventions("managed_restart",[x.get("name") for x in down],outcome,started_at,completed_at,3.0)
        self.store.record_decision(source="VM_Intelligence",action=decision.action,
            authority=decision.authority,risk="low",confidence=.98,reason=decision.reason,
            outcome=outcome,metadata={"down":[x.get("name") for x in down],"result":result})
        actions.append({"action":"supervise_once","down":[x.get("name") for x in down],
                        "outcome":outcome,"result":result})
        return actions
