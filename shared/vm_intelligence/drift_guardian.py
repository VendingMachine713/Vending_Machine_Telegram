from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json
from pathlib import Path

from .v42_schema import ensure_v42_schema

def _now():return datetime.now(timezone.utc).isoformat()

def _sev_weight(sev):return {"critical":35,"high":25,"medium":10,"low":3}.get(sev,5)

def _registry_hash(services):
    stable=[]
    for s in sorted(services,key=lambda x:x.get("service","")):
        stable.append({
            "service":s.get("service"),"runtime_id":s.get("runtime_id"),
            "canonical_entrypoint":s.get("canonical_entrypoint"),
            "compatibility_entrypoint":s.get("compatibility_entrypoint"),
            "source_hash":s.get("source_hash"),"topology_hash":s.get("topology_hash"),
            "managed":bool(s.get("managed")),"auto_start":bool(s.get("auto_start")),
            "auto_restart":bool(s.get("auto_restart")),
        })
    return hashlib.sha256(json.dumps(stable,sort_keys=True,default=str).encode()).hexdigest()

class DriftGuardian:
    """Read-only platform drift detector with proposal-only remediation."""
    def __init__(self,store,root):self.store=store;self.root=Path(root);ensure_v42_schema(store)

    def _previous_services(self):
        with self.store.connect() as con:
            return {r["service"]:dict(r) for r in con.execute("SELECT * FROM platform_services").fetchall()}

    def evaluate(self,services,configs,normalization):
        now=_now();findings=[]
        for svc in services:
            name=svc["service"]
            # Drift means a change from a previously observed canonical baseline.
            # Known static architecture debt belongs to PlatformNormalizer, not here.
            if svc.get("runtime_identity_changed"):
                findings.append({"service":name,"category":"runtime_identity_changed","severity":"high",
                                 "title":"Canonical runtime identity changed since previous registry observation","automatic":False,
                                 "evidence":{"previous_runtime_id":svc.get("previous_runtime_id"),"current_runtime_id":svc.get("runtime_id")}})
            if svc.get("source_changed"):
                findings.append({"service":name,"category":"canonical_source_changed","severity":"medium",
                                 "title":"Canonical source hash changed since previous observation","automatic":False,
                                 "evidence":{"previous_source_hash":svc.get("previous_source_hash"),"current_source_hash":svc.get("source_hash")}})
            if svc.get("topology_changed"):
                findings.append({"service":name,"category":"topology_changed","severity":"medium",
                                 "title":"Canonical runtime topology changed since previous observation","automatic":False,
                                 "evidence":{"previous_topology_hash":svc.get("previous_topology_hash"),"current_topology_hash":svc.get("topology_hash")}})
        for cfg in configs:
            if not cfg.get("exists"):
                findings.append({"service":cfg.get("service"),"category":"missing_registered_config","severity":"high",
                                 "title":"Previously discovered configuration path is missing","automatic":False,
                                 "evidence":{"path":cfg.get("path")}})
        score=max(0.0,100.0-sum(_sev_weight(x.get("severity")) for x in findings))
        counts={sev:sum(1 for x in findings if x.get("severity")==sev) for sev in ("critical","high","medium","low")}
        proposals=[]
        for f in findings:
            cat=f.get("category")
            action={
                "runtime_identity_changed":"review_runtime_identity_change",
                "canonical_source_changed":"review_canonical_source_change",
                "topology_changed":"review_runtime_topology_change",
                "missing_registered_config":"restore_or_repoint_config_after_validation",
            }.get(cat,"review_architecture_drift")
            proposals.append({"service":f.get("service"),"action":action,"automatic":False,
                              "reason":f.get("title"),"risk":"medium" if f.get("severity") in {"medium","high"} else "low"})
        rh=_registry_hash(services)
        with self.store.connect() as con:
            con.execute("""INSERT INTO platform_drift_snapshots(observed_at_utc,score,high_count,medium_count,low_count,findings_json,registry_hash)
                VALUES(?,?,?,?,?,?,?)""",(now,score,counts["high"]+counts["critical"],counts["medium"],counts["low"],
                                          json.dumps(findings,sort_keys=True,default=str),rh))
        out={"score":round(score,1),"counts":counts,"findings":findings,
             "proposals":sorted(proposals,key=lambda x:(x["service"],x["action"])),
             "registry_hash":rh,"automatic_mutation":False,
             "architecture_hygiene_score":normalization.get("score"),
             "architecture_hygiene_findings":len(normalization.get("violations",[])),
             "note":"Drift tracks changes from baseline. Static topology debt remains in Platform Normalisation and is proposal-only."}

        p=self.root/"diagnostics"/"platform_drift.json";p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(out,indent=2,default=str),encoding="utf-8")
        return out
