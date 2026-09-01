from __future__ import annotations

class EfficiencyBrain:
    def analyze(self, integrated, techdebt):
        findings=[]
        sap=integrated.get("Smart_Auto_Poster_V2",{}).get("metrics",{})
        retries=(sap.get("queue_retry") or 0)+(sap.get("queue_deferred") or 0)
        if retries>=5:
            findings.append({"source":"Smart_Auto_Poster_V2","score":85,
                "title":"Reduce repeated queue work",
                "detail":f"{int(retries)} retry/deferred queue items are active; analyse dominant error kinds and batch transient recovery."})
        if (sap.get("account_failure_streaks") or 0)>=3:
            findings.append({"source":"Smart_Auto_Poster_V2","score":78,
                "title":"Reduce account failure churn",
                "detail":f"Combined account failure streak count is {int(sap['account_failure_streaks'])}."})
        rm=integrated.get("VM_Relationship_Manager",{}).get("metrics",{})
        if (rm.get("integration_pending") or 0)>=20:
            findings.append({"source":"VM_Relationship_Manager","score":70,
                "title":"Drain Relationship Manager integration backlog",
                "detail":f"{int(rm['integration_pending'])} integration events are pending."})
        duplicates=len((techdebt or {}).get("duplicate_groups") or [])
        if duplicates:
            findings.append({"source":"VM_Core","score":min(90,55+duplicates*2),
                "title":"Consolidate exact duplicate implementation",
                "detail":f"{duplicates} exact duplicate Python groups increase maintenance effort."})
        large=len((techdebt or {}).get("large_files") or [])
        if large:
            findings.append({"source":"VM_Core","score":min(80,45+large*5),
                "title":"Split oversized modules along stable seams",
                "detail":f"{large} modules exceed the maintainability threshold."})
        findings.sort(key=lambda x:-x["score"])
        return findings
