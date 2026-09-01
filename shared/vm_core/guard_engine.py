from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
from typing import Any
from .paths import project_root
from .db import PlatformDB
from .health import run_health
from .backup import list_backups
from .logging_setup import tail_logs
from .components import read_components

def _hours_since(ts: float) -> float:
    return (datetime.now(timezone.utc).timestamp()-ts)/3600

def guard_pass(root: Path | None = None) -> dict[str,Any]:
    root=root or project_root()
    db=PlatformDB(root=root); db.init()
    alerts=[]
    active_keys=set()
    health=run_health(root)
    for item in health:
        status=item["status"]; service=item["service"]
        if status in {"DEGRADED","FAILED"}:
            key=f"health:{service}"; active_keys.add(key)
            aid=db.upsert_alert(key,"ERROR","VM_Guard",
                f"{service} health is {status}",json.dumps(item["detail"],default=str)[:3000])
            alerts.append(aid)
        elif status=="CONFIG_REQUIRED":
            key=f"config:{service}"; active_keys.add(key)
            aid=db.upsert_alert(key,"WARN","VM_Guard",
                f"{service} requires configuration",
                ", ".join(item["detail"].get("configuration",{}).get("missing_env_names",[])))
            alerts.append(aid)

    free=shutil.disk_usage(root).free/(1024**3)
    if free < 2:
        active_keys.add("disk:critical")
        alerts.append(db.upsert_alert("disk:critical","CRITICAL","VM_Guard",
            "Low disk space",f"{free:.1f} GiB free"))
    elif free < 5:
        active_keys.add("disk:low")
        alerts.append(db.upsert_alert("disk:low","WARN","VM_Guard",
            "Disk space getting low",f"{free:.1f} GiB free"))

    backups=list_backups(root)
    if not backups:
        active_keys.add("backup:none")
        alerts.append(db.upsert_alert("backup:none","WARN","VM_Guard","No VM platform backup found","Create a backup."))
    else:
        age=_hours_since(backups[0].stat().st_mtime)
        if age > 36:
            active_keys.add("backup:stale")
            alerts.append(db.upsert_alert("backup:stale","WARN","VM_Guard",
                "Latest VM backup is stale",f"{age:.1f} hours old"))

    failed=[j for j in db.jobs(100) if j["status"]=="FAILED"]
    if failed:
        active_keys.add("jobs:failed")
        alerts.append(db.upsert_alert("jobs:failed","ERROR","VM_Guard",
            f"{len(failed)} failed platform job(s)",
            "; ".join(f"#{j['id']} {j['job_type']}: {j['last_error'] or ''}" for j in failed[:10])))

    error_lines=tail_logs("platform",200,errors_only=True,root=root)
    if len(error_lines) >= 5:
        active_keys.add("logs:error_burst")
        alerts.append(db.upsert_alert("logs:error_burst","WARN","VM_Guard",
            "Platform error/warning burst detected",f"{len(error_lines)} recent warning/error log lines"))

    components=read_components(root)
    now=datetime.now(timezone.utc)
    for service,comp in components.items():
        raw=comp.get("updated_at_utc")
        age=None
        if raw:
            try:
                dt=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
                if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
                age=(now-dt.astimezone(timezone.utc)).total_seconds()
            except Exception:
                age=None
        if age is not None and age > 180:
            key=f"component:{service}:stale"; active_keys.add(key)
            alerts.append(db.upsert_alert(key,"WARN","VM_Guard",
                f"{service} component heartbeat is stale",f"Last heartbeat {age:.0f} seconds ago"))
        legacy=comp.get("legacy_component") or {}
        if comp.get("legacy_component_expected") and not legacy.get("alive"):
            key=f"component:{service}:legacy"; active_keys.add(key)
            alerts.append(db.upsert_alert(key,"ERROR","VM_Guard",
                f"{service} legacy Telegram component is not alive",
                str(legacy.get("error") or legacy.get("restart_in_seconds") or "restart pending")))

    resolved=db.resolve_alerts_except("VM_Guard",active_keys)
    return {
        "checked_at_utc":datetime.now(timezone.utc).isoformat(),
        "health":{x["service"]:x["status"] for x in health},
        "new_or_refreshed_alert_ids":alerts,
        "open_alerts":len(db.alerts(500)),
        "resolved_alerts_this_pass":resolved,
        "disk_free_gib":round(free,2),
        "latest_backup":str(backups[0]) if backups else None,
    }
