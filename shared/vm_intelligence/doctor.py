from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import json
from .store import IntelligenceStore
from .v4_schema import ensure_v4_schema
from .v42_schema import ensure_v42_schema
from .v5_schema import ensure_v5_schema
from .v6_schema import ensure_v6_schema
from . import __version__

EXPECTED_VERSION="6.0.0"

def run_doctor(root):
    root=Path(root);checks=[]
    checks.append({"check":"package_version","ok":__version__==EXPECTED_VERSION,
                   "detail":{"running":__version__,"expected":EXPECTED_VERSION}})
    cfg=root/"config"/"vm_intelligence.json"
    if cfg.is_file():
        try:
            parsed=json.loads(cfg.read_text(encoding="utf-8-sig"))
            checks.append({"check":"config_json","ok":isinstance(parsed,dict),"detail":str(cfg)})
        except Exception as exc:
            checks.append({"check":"config_json","ok":False,"detail":type(exc).__name__})
    else:
        checks.append({"check":"config_json","ok":False,"detail":"missing config/vm_intelligence.json"})

    marker=root/"state"/"vm_intelligence_release.json"
    source_workspace=not marker.is_file()
    if marker.is_file():
        try:
            release=json.loads(marker.read_text(encoding="utf-8-sig"))
            checks.append({"check":"release_marker","ok":str(release.get("version"))==EXPECTED_VERSION,
                           "detail":release.get("version")})
        except Exception as exc:
            checks.append({"check":"release_marker","ok":False,"detail":type(exc).__name__})
    else:
        checks.append({"check":"release_marker","ok":True,"detail":"source workspace mode"})

    db=root/"state"/"vm_intelligence.sqlite3"
    checks.append({"check":"database_exists","ok":db.is_file(),"detail":str(db)})
    if db.is_file():
        try:
            store=IntelligenceStore(db);ensure_v4_schema(store);ensure_v42_schema(store);ensure_v5_schema(store);ensure_v6_schema(store)
            with store.connect() as con:
                quick=[r[0] for r in con.execute("PRAGMA quick_check").fetchall()]
                schema=con.execute("SELECT value FROM intelligence_meta WHERE key='schema_version'").fetchone()
                last=con.execute("SELECT completed_at_utc,status FROM intelligence_cycles ORDER BY cycle_id DESC LIMIT 1").fetchone()
            checks.append({"check":"database_integrity","ok":all(str(x).lower()=="ok" for x in quick),"detail":quick})
            checks.append({"check":"schema_version","ok":bool(schema and str(schema[0])=="12"),"detail":schema[0] if schema else None})
            if last:
                dt=datetime.fromisoformat(str(last[0]).replace("Z","+00:00"))
                age=(datetime.now(timezone.utc)-dt).total_seconds()
                checks.append({"check":"recent_cycle","ok":age<=900 and last[1]=="ok",
                               "detail":{"age_seconds":round(age,1),"status":last[1]}})
            else:
                checks.append({"check":"recent_cycle","ok":False,"detail":"no cycle recorded"})
        except Exception as exc:
            checks.append({"check":"database_open","ok":False,"detail":type(exc).__name__})

    report=root/"diagnostics"/"intelligence_report.json"
    checks.append({"check":"report_exists","ok":report.is_file(),"detail":str(report)})
    registry=root/"state"/"runtime_registry.json"
    checks.append({"check":"runtime_registry","ok":registry.is_file() or source_workspace,
                   "detail":str(registry) if registry.is_file() else "source workspace mode"})
    bridge=root/"state"/"runtime_bridge.json"
    checks.append({"check":"runtime_bridge","ok":bridge.is_file() or source_workspace,
                   "detail":str(bridge) if bridge.is_file() else "source workspace mode"})
    platform_registry=root/"state"/"platform_service_registry.json"
    checks.append({"check":"platform_service_registry","ok":platform_registry.is_file() or source_workspace,
                   "detail":str(platform_registry) if platform_registry.is_file() else "source workspace mode"})
    config_registry=root/"state"/"config_registry.json"
    checks.append({"check":"config_registry","ok":config_registry.is_file() or source_workspace,
                   "detail":str(config_registry) if config_registry.is_file() else "source workspace mode"})
    drift=root/"diagnostics"/"platform_drift.json"
    checks.append({"check":"platform_drift","ok":drift.is_file() or source_workspace,
                   "detail":str(drift) if drift.is_file() else "source workspace mode"})
    planner=root/"diagnostics"/"intelligence_strategic_planner_v5.json"
    checks.append({"check":"v5_strategic_planner","ok":planner.is_file() or source_workspace,
                   "detail":str(planner) if planner.is_file() else "source workspace mode"})
    trust=root/"diagnostics"/"intelligence_capability_trust_v5.json"
    checks.append({"check":"v5_capability_trust","ok":trust.is_file() or source_workspace,
                   "detail":str(trust) if trust.is_file() else "source workspace mode"})
    predictive=root/"diagnostics"/"intelligence_predictive_v5.json"
    checks.append({"check":"v5_predictive_ops","ok":predictive.is_file() or source_workspace,
                   "detail":str(predictive) if predictive.is_file() else "source workspace mode"})
    evidence=root/"diagnostics"/"intelligence_evidence_v6.json"
    checks.append({"check":"v6_evidence_truth","ok":evidence.is_file() or source_workspace,
                   "detail":str(evidence) if evidence.is_file() else "source workspace mode"})
    policy=root/"diagnostics"/"intelligence_policy_kernel_v6.json"
    checks.append({"check":"v6_policy_kernel","ok":policy.is_file() or source_workspace,
                   "detail":str(policy) if policy.is_file() else "source workspace mode"})
    operator=root/"diagnostics"/"intelligence_strategic_operator_v6.json"
    checks.append({"check":"v6_strategic_operator","ok":operator.is_file() or source_workspace,
                   "detail":str(operator) if operator.is_file() else "source workspace mode"})
    dr=root/"diagnostics"/"intelligence_disaster_recovery_v6.json"
    checks.append({"check":"v6_disaster_recovery","ok":dr.is_file() or source_workspace,
                   "detail":str(dr) if dr.is_file() else "source workspace mode"})
    admin_root=root/"bots"/"Admin_Command_Centre"
    admin_candidates=list(admin_root.glob("**/admin_core.py")) if admin_root.exists() else []
    patched=False
    for p in admin_candidates:
        try:
            if "VM_INTELLIGENCE_V3_DISPATCH_BEGIN" in p.read_text(encoding="utf-8-sig",errors="ignore"):
                patched=True;break
        except Exception:
            pass
    checks.append({"check":"admin_cockpit_patch","ok":patched,"detail":"v3 dispatch marker"})
    result={"ok":all(x["ok"] for x in checks),"version":__version__,
            "generated_at_utc":datetime.now(timezone.utc).isoformat(),"checks":checks}
    diag=root/"diagnostics";diag.mkdir(parents=True,exist_ok=True)
    (diag/"intelligence_doctor.json").write_text(json.dumps(result,indent=2,default=str),encoding="utf-8")
    return result
