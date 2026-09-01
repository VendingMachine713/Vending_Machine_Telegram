from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from datetime import datetime, timezone

EXCLUDED={"archive","backups","venv",".venv","__pycache__",".git","node_modules","runtime","sessions"}
LAUNCHERS=(
    "START_ADMIN_COMMAND_CENTRE.bat","START.ps1","START.bat","START.cmd",
    "START_VM_RELATIONSHIPS.ps1","START_VM_RELATIONSHIPS.bat","RUN_SERVICE.ps1"
)

def read_json(path:Path):
    try:return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:return {}

def excluded(path:Path)->bool:
    return any(part.lower() in EXCLUDED for part in path.parts)

def resolve_inside(base:Path,value):
    if not value:return None
    p=Path(str(value))
    return p if p.is_absolute() else (base/p).resolve()

def discover_runtime(root:Path,bot_name:str):
    bot=root/"bots"/bot_name
    if not bot.is_dir():
        return {"ok":False,"bot":bot_name,"reason":"bot_not_found","candidates":[]}
    candidates=[]
    for manifest in bot.glob("**/BOT_MANIFEST.json"):
        if excluded(manifest):continue
        data=read_json(manifest)
        declared=str(data.get("name") or "")
        if declared and declared!=bot_name:continue
        entry=data.get("entrypoint")
        ep=resolve_inside(manifest.parent,entry)
        if not ep or not ep.is_file():continue
        cls=str(data.get("classification") or "").upper()
        conf=str(data.get("entrypoint_confidence") or "").lower()
        lifecycle=data.get("lifecycle") or {}
        score=1000
        if cls=="CANONICAL":score+=300
        if conf=="high":score+=100
        if lifecycle:score+=50
        if manifest.parent==bot:score+=40
        if (manifest.parent/"tests").is_dir():score+=20
        launcher=None
        raw_launcher=data.get("launcher")
        lp=resolve_inside(manifest.parent,raw_launcher)
        if lp and lp.is_file():
            launcher=lp
        else:
            for name in LAUNCHERS:
                p=manifest.parent/name
                if p.is_file():
                    launcher=p.resolve();break
        candidates.append({
            "score":score,"manifest":str(manifest.resolve()),"runtime_dir":str(manifest.parent.resolve()),
            "entrypoint_abs":str(ep.resolve()),"entrypoint_name":ep.name,
            "launcher_abs":str(launcher) if launcher else None,
            "classification":cls or None,"confidence":conf or None,
            "lifecycle":lifecycle,"version":data.get("version")
        })
    # Fallback to obvious direct runnable files only if no valid manifest candidate exists.
    if not candidates:
        for name in ("main.py","app.py"):
            for ep in bot.glob(f"**/{name}"):
                if excluded(ep):continue
                score=500-min(100,len(ep.relative_to(bot).parts))
                candidates.append({
                    "score":score,"manifest":None,"runtime_dir":str(ep.parent.resolve()),
                    "entrypoint_abs":str(ep.resolve()),"entrypoint_name":ep.name,
                    "launcher_abs":None,"classification":None,"confidence":"inferred",
                    "lifecycle":{},"version":None
                })
    candidates=sorted(candidates,key=lambda x:(-x["score"],len(x["entrypoint_abs"]),x["entrypoint_abs"].casefold()))
    if not candidates:
        return {"ok":False,"bot":bot_name,"reason":"no_runnable_candidate","candidates":[]}
    return {"ok":True,"bot":bot_name,"selected":candidates[0],"candidates":candidates[:12]}

def rel_posix(path:Path,base:Path)->str:
    return Path(os.path.relpath(path,base)).as_posix()

def repair_outer_manifest(root:Path,bot_name:str,backup_dir:Path|None=None,apply:bool=False):
    result=discover_runtime(root,bot_name)
    if not result.get("ok"):return result
    bot=root/"bots"/bot_name
    selected=result["selected"]
    outer=bot/"BOT_MANIFEST.json"
    outer_existed=outer.is_file()
    before=read_json(outer) if outer_existed else {}
    after=dict(before)
    current_ep=resolve_inside(bot,before.get("entrypoint"))
    current_valid=bool(current_ep and current_ep.is_file())
    selected_ep=Path(selected["entrypoint_abs"])
    selected_launcher=Path(selected["launcher_abs"]) if selected.get("launcher_abs") else None
    changed=False

    if not current_valid:
        after["entrypoint"]=rel_posix(selected_ep,bot);changed=True
        after["entrypoint_confidence"]="high"
    if not after.get("name"):
        after["name"]=bot_name;changed=True
    if str(after.get("classification") or "").upper()!="CANONICAL":
        after["classification"]="CANONICAL";changed=True
    current_launcher=resolve_inside(bot,before.get("launcher"))
    if (not current_launcher or not current_launcher.is_file()) and selected_launcher and selected_launcher.is_file():
        after["launcher"]=rel_posix(selected_launcher,bot);changed=True
    if not after.get("lifecycle") and selected.get("lifecycle"):
        after["lifecycle"]=selected["lifecycle"];changed=True
    after["runtime_resolution"]={
        "source":"VM_Intelligence_v5.0.0",
        "selected_manifest":rel_posix(Path(selected["manifest"]),root) if selected.get("manifest") else None,
        "selected_runtime_dir":rel_posix(Path(selected["runtime_dir"]),root),
        "resolved_at_utc":datetime.now(timezone.utc).isoformat(),
    }

    backup=None
    if apply and changed:
        if backup_dir:
            backup=backup_dir/"runtime_manifests"/bot_name/"BOT_MANIFEST.json"
            backup.parent.mkdir(parents=True,exist_ok=True)
            if outer.is_file():
                backup.write_bytes(outer.read_bytes())
        outer.parent.mkdir(parents=True,exist_ok=True)
        outer.write_text(json.dumps(after,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return {
        **result,"outer_manifest":str(outer),"outer_existed":outer_existed,"before":before,"after":after,
        "changed":changed,"applied":bool(apply and changed),"backup":str(backup) if backup else None,
        "entrypoint_relative":after.get("entrypoint"),"launcher_relative":after.get("launcher"),
        "auto_start":bool((after.get("lifecycle") or {}).get("auto_start",False)),
        "auto_restart":bool((after.get("lifecycle") or {}).get("auto_restart",False)),
    }

def verify_vm_core_services(root:Path,bot_names):
    sys.path.insert(0,str(root))
    try:
        from shared.vm_core.services import service_status, restart_service
    except Exception as exc:
        return {"ok":False,"error":f"{type(exc).__name__}: {exc}","services":[]}
    try: rows=service_status(root)
    except Exception as exc:
        return {"ok":False,"error":f"service_status:{type(exc).__name__}:{exc}","services":[]}
    by={str(x.get("name")):x for x in rows}
    out=[];ok=True
    for name in bot_names:
        row=by.get(name)
        dry=None
        if row:
            try:dry=restart_service(name,root,dry_run=True,background=True)
            except Exception as exc:dry={"ok":False,"error":f"{type(exc).__name__}:{exc}"}
        start=(dry or {}).get("start") if isinstance(dry,dict) else None
        runnable=bool(row and (row.get("entrypoint") or row.get("launcher")))
        dry_text=json.dumps(dry or {},default=str).lower()
        dry_ok=not bool((dry or {}).get("error")) and "no runnable entrypoint or launcher detected" not in dry_text
        svc_ok=runnable and dry_ok
        ok &= svc_ok
        out.append({"name":name,"ok":svc_ok,"status":row,"dry_run":dry})
    return {"ok":bool(ok),"error":None if ok else "one_or_more_services_not_runnable","services":out}


def restore_applied_repairs(results):
    restored=[]
    for row in results:
        if not row.get("applied"):continue
        outer=Path(row["outer_manifest"])
        backup=row.get("backup")
        if backup and Path(backup).is_file():
            outer.parent.mkdir(parents=True,exist_ok=True)
            outer.write_bytes(Path(backup).read_bytes())
            restored.append(row["bot"])
        elif not row.get("outer_existed"):
            outer.unlink(missing_ok=True)
            restored.append(row["bot"])
    return restored

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True)
    p.add_argument("--backup-dir")
    p.add_argument("--report",required=True)
    p.add_argument("--apply",action="store_true")
    p.add_argument("--verify-services",action="store_true")
    p.add_argument("--bots",nargs="+",default=["Admin_Command_Centre","Universal_Search","VM_Guard"])
    a=p.parse_args(argv)
    root=Path(a.root).resolve()
    backup=Path(a.backup_dir).resolve() if a.backup_dir else None
    results=[repair_outer_manifest(root,b,backup,apply=a.apply) for b in a.bots]
    payload={"schema_version":1,"root":str(root),"apply":a.apply,"bots":results}
    if a.verify_services:
        payload["vm_core_verification"]=verify_vm_core_services(root,a.bots)
    else:
        payload["vm_core_verification"]={"ok":True,"skipped":True}
    payload["ok"]=all(x.get("ok") for x in results) and payload["vm_core_verification"].get("ok",False)
    if a.apply and not payload["ok"]:
        payload["rolled_back"]=restore_applied_repairs(results)
    else:
        payload["rolled_back"]=[]
    report=Path(a.report);report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(payload,indent=2,default=str)+"\n",encoding="utf-8")
    print(json.dumps({
        "ok":payload["ok"],
        "changed":[x["bot"] for x in results if x.get("changed")],
        "applied":[x["bot"] for x in results if x.get("applied")],
        "report":str(report),
        "vm_core_verification":payload["vm_core_verification"],
        "bots":[{"bot":x.get("bot"),"changed":x.get("changed"),"applied":x.get("applied"),
                 "entrypoint_abs":(x.get("selected") or {}).get("entrypoint_abs"),
                 "runtime_dir":(x.get("selected") or {}).get("runtime_dir"),
                 "auto_start":x.get("auto_start"),"auto_restart":x.get("auto_restart")}
                for x in results],
        "rolled_back":payload.get("rolled_back",[]),
    },default=str))
    return 0 if payload["ok"] else 4

if __name__=="__main__":
    raise SystemExit(main())
