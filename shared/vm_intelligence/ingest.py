from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json
from .events import Event

def _stable_id(kind:str, path:Path, marker:str) -> str:
    sig=f"{kind}|{path.name}|{path.stat().st_mtime_ns if path.exists() else 0}|{marker}"
    return hashlib.sha256(sig.encode()).hexdigest()

def _event(**kwargs):
    return Event(**kwargs)

def ingest_vm_diagnostics(store, project_root: str | Path) -> int:
    root=Path(project_root); diag=root/"diagnostics"; count=0
    health=diag/"health_report.json"
    if health.exists():
        try:
            rows=json.loads(health.read_text(encoding="utf-8-sig"))
            for i,item in enumerate(rows if isinstance(rows,list) else []):
                status=str(item.get("status","UNKNOWN")).upper()
                outcome="success" if status in {"READY","ALIVE","RUNNING","PASS"} else "failure"
                e=Event(source=str(item.get("service","unknown")),kind="health",action="platform_health",
                    outcome=outcome,level="info" if outcome=="success" else "warning",
                    metadata={"status":status},event_id=_stable_id("health",health,f"{i}:{item.get('service')}:{status}"))
                count += int(store.add_event(e))
        except Exception: pass

    doctor=diag/"latest_diagnostic.json"
    if doctor.exists():
        try:
            data=json.loads(doctor.read_text(encoding="utf-8-sig"))
            for i,check in enumerate(data.get("checks",[])):
                status=str(check.get("status","INFO")).upper()
                source=str(check.get("name","platform")).split(":",1)[0]
                outcome="failure" if status=="FAIL" else "success" if status=="PASS" else "unknown"
                level="error" if status=="FAIL" else "warning" if status=="WARN" else "info"
                e=Event(source=source,kind="diagnostic",action=str(check.get("category","check")),
                    outcome=outcome,level=level,metadata={"check":check.get("name"),"status":status},
                    event_id=_stable_id("doctor",doctor,f"{i}:{check.get('name')}:{status}"))
                count += int(store.add_event(e))
        except Exception: pass

    alerts=diag/"open_alerts.json"
    if alerts.exists():
        try:
            rows=json.loads(alerts.read_text(encoding="utf-8-sig"))
            for i,alert in enumerate(rows if isinstance(rows,list) else []):
                raw=str(alert.get("severity","warning")).lower()
                level=raw if raw in {"debug","info","warning","error","critical"} else "warning"
                e=Event(source=str(alert.get("source","VM_Core")),kind="alert",
                    action=str(alert.get("type",alert.get("dedupe_key","open_alert"))),outcome="failure",level=level,
                    metadata={"alert_id":alert.get("id"),"title":alert.get("title")},
                    event_id=_stable_id("alert",alerts,f"{i}:{alert.get('id')}:{alert.get('last_seen_utc')}"))
                count += int(store.add_event(e))
        except Exception: pass

    runtime=diag/"live_runtime.json"
    if runtime.exists():
        try:
            data=json.loads(runtime.read_text(encoding="utf-8-sig"))
            stamp=data.get("generated_at_utc") or datetime.fromtimestamp(runtime.stat().st_mtime,tz=timezone.utc).isoformat()
            for svc in data.get("services",[]):
                alive=bool(svc.get("process_alive"))
                e=Event(source=str(svc.get("name","unknown")),kind="runtime",action="process_state",
                    outcome="success" if alive else "skipped",level="info",
                    metadata={"runtime_status":svc.get("runtime_status"),"process_alive":alive,"observed_at":stamp},
                    event_id=_stable_id("runtime",runtime,f"{svc.get('name')}:{stamp}:{alive}"))
                count += int(store.add_event(e))
            for a in data.get("open_alerts",[]):
                e=Event(source=str(a.get("source","VM_Core")),kind="alert",action=str(a.get("dedupe_key","runtime_alert")),
                    outcome="failure",level="warning",metadata={"title":a.get("title"),"occurrences":a.get("occurrences")},
                    event_id=_stable_id("runtime_alert",runtime,f"{a.get('id')}:{a.get('last_seen_utc')}"))
                count += int(store.add_event(e))
        except Exception: pass

    validation=diag/"full_validation.json"
    if validation.exists():
        try:
            data=json.loads(validation.read_text(encoding="utf-8-sig"))
            stamp=data.get("completed_at_utc","")
            for bot,status in data.get("health",{}).items():
                ok=str(status).upper() in {"READY","ALIVE","RUNNING","PASS"}
                e=Event(source=bot,kind="validation",action="full_validation",outcome="success" if ok else "failure",
                    level="info" if ok else "warning",metadata={"status":status,"observed_at":stamp},
                    event_id=_stable_id("validation",validation,f"{bot}:{status}:{stamp}"))
                count += int(store.add_event(e))
        except Exception: pass
    return count
