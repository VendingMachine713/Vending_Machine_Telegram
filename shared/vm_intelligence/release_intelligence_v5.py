from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json
from pathlib import Path
from .v5_schema import ensure_v5_schema

def _now():return datetime.now(timezone.utc).isoformat()

RISK_WEIGHTS={
    ".md":2,".txt":2,".json":8,".toml":10,".ini":10,".cfg":10,
    ".py":20,".ps1":24,".bat":20,".sql":35,
}
CRITICAL_FRAGMENTS=("shared/vm_core","migrations","schema","runtime_bridge","admin_core","telegram","delivery")

class ReleaseIntelligence:
    def __init__(self,store,root):self.store=store;self.root=Path(root);ensure_v5_schema(store)

    def impact(self,changed_files,dependency_edges):
        services=set();risk=0.0;reasons=[]
        edges=list(dependency_edges or [])
        for raw in changed_files:
            p=str(raw).replace("\\","/")
            suffix=Path(p).suffix.lower()
            risk+=RISK_WEIGHTS.get(suffix,12)
            if any(x in p.lower() for x in CRITICAL_FRAGMENTS):
                risk+=25;reasons.append(f"critical_surface:{p}")
            for e in edges:
                src=str(e.get("source","")).replace("\\","/")
                if src and (src in p or p in src):
                    services.add(str(e.get("target")))
        risk=min(100.0,risk)
        tests=[]
        mapping={
            "Admin_Command_Centre":"Admin Command Centre",
            "Universal_Search":"Universal Search",
            "VM_Guard":"VM Guard",
            "Smart_Auto_Poster_V2":"Smart Auto Poster",
            "VM_Relationship_Manager":"Relationship Manager",
        }
        for svc in sorted(services):
            tests.append(mapping.get(svc,svc))
        if risk>=70:
            tests=["ALL_CANONICAL"]+tests
        return {"risk_score":round(risk,1),"blast_radius":sorted(services),
                "selected_test_suites":list(dict.fromkeys(tests)),"reasons":reasons}

    def gate(self,release_key,changed_files,dependency_edges,baseline=None,observed=None):
        impact=self.impact(changed_files,dependency_edges)
        baseline=baseline or {};observed=observed or {}
        regressions=[]
        for key in ("overall_score","slo_compliance_pct","security_score"):
            if key in baseline and key in observed and observed[key] < baseline[key]:
                regressions.append({"metric":key,"before":baseline[key],"after":observed[key]})
        gate="reject" if regressions or impact["risk_score"]>=95 else "observe" if impact["risk_score"]>=60 else "accept_candidate"
        confidence=max(.4,min(.99,1.0-impact["risk_score"]/200.0))
        now=_now()
        with self.store.connect() as con:
            con.execute("""INSERT INTO release_candidates(release_key,risk_score,confidence,blast_radius_json,
              selected_tests_json,gate_status,baseline_json,observed_json,decision,created_at_utc,updated_at_utc)
              VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(release_key) DO UPDATE SET risk_score=excluded.risk_score,
              confidence=excluded.confidence,blast_radius_json=excluded.blast_radius_json,
              selected_tests_json=excluded.selected_tests_json,gate_status=excluded.gate_status,
              baseline_json=excluded.baseline_json,observed_json=excluded.observed_json,
              decision=excluded.decision,updated_at_utc=excluded.updated_at_utc""",
              (release_key,impact["risk_score"],confidence,json.dumps(impact["blast_radius"]),
               json.dumps(impact["selected_test_suites"]),gate,json.dumps(baseline,sort_keys=True),
               json.dumps(observed,sort_keys=True),gate,now,now))
        return {**impact,"release_key":release_key,"gate_status":gate,"confidence":round(confidence,2),
                "regressions":regressions,"automatic_promotion":False}
