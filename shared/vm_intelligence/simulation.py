from __future__ import annotations

class SimulationEngine:
    """Conservative what-if evaluator. Refuses unsupported guesses."""
    def simulate(self,action,integrated):
        raw=(action or "").strip().lower()
        if raw.startswith("restart "):
            service=action.split(None,1)[1].strip()
            data=integrated.get(service,{})
            m=data.get("metrics",{})
            if m.get("auto_restart")!=1:
                return {"supported":True,"decision":"approval_required","risk":"medium",
                        "expected":"Service is outside automatic restart policy.","service":service}
            return {"supported":True,"decision":"safe_candidate","risk":"low",
                    "expected":"Restore process availability using VM Core's existing restart path.",
                    "rollback":"Process can be stopped/restarted again; no data mutation is planned.","service":service}
        if "worker" in raw or "concurrency" in raw:
            return {"supported":False,"decision":"insufficient_evidence","risk":"unknown",
                    "expected":"No concurrency change simulated because CPU/API-pressure response has not been experimentally measured."}
        if "delete" in raw or "purge" in raw:
            return {"supported":True,"decision":"blocked","risk":"critical",
                    "expected":"Destructive operation is outside Intelligence's autonomous safety boundary."}
        return {"supported":False,"decision":"unknown_action","risk":"unknown",
                "expected":"No trustworthy simulation model exists for this action yet."}
