from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

MANAGED = ("Admin_Command_Centre","Universal_Search","VM_Guard")
EXCLUDED = {"archive","backups","venv",".venv","__pycache__",".git","node_modules","runtime","sessions"}
MARKER = "VM_INTELLIGENCE_RUNTIME_BRIDGE_V307"

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def read_json(path:Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}

def write_json(path:Path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")

def excluded(path:Path):
    return any(part.lower() in EXCLUDED for part in path.parts)

def _resolve(base:Path,value):
    if not value:return None
    p=Path(str(value))
    return p if p.is_absolute() else (base/p).resolve()

def discover_nested(root:Path,bot_name:str):
    bot=root/"bots"/bot_name
    if not bot.is_dir():
        return {"ok":False,"reason":"bot_not_found","bot":bot_name}
    candidates=[]
    for manifest in bot.glob("**/BOT_MANIFEST.json"):
        if manifest == bot/"BOT_MANIFEST.json" or excluded(manifest):
            continue
        data=read_json(manifest)
        if data.get("name") and str(data.get("name")) != bot_name:
            continue
        ep=_resolve(manifest.parent,data.get("entrypoint"))
        if not ep or not ep.is_file():
            continue
        score=0
        if str(data.get("classification") or "").upper()=="CANONICAL":score+=300
        if str(data.get("entrypoint_confidence") or "").lower()=="high":score+=100
        if (manifest.parent/"tests").is_dir():score+=25
        score-=len(manifest.relative_to(bot).parts)
        candidates.append({
            "score":score,"manifest":str(manifest.resolve()),
            "runtime_dir":str(manifest.parent.resolve()),
            "entrypoint_abs":str(ep.resolve()),"entrypoint_name":ep.name,
            "lifecycle":data.get("lifecycle") or {},"version":data.get("version"),
        })
    if not candidates:
        for name in ("main.py","app.py"):
            for ep in bot.glob(f"**/{name}"):
                if ep.parent==bot or excluded(ep):continue
                candidates.append({
                    "score":50-len(ep.relative_to(bot).parts),"manifest":None,
                    "runtime_dir":str(ep.parent.resolve()),"entrypoint_abs":str(ep.resolve()),
                    "entrypoint_name":ep.name,"lifecycle":{},"version":None,
                })
    candidates.sort(key=lambda x:(-x["score"],len(x["entrypoint_abs"]),x["entrypoint_abs"].casefold()))
    if not candidates:
        return {"ok":False,"reason":"nested_canonical_runtime_not_found","bot":bot_name}
    return {"ok":True,"bot":bot_name,"selected":candidates[0],"candidates":candidates[:12]}

def validated_policy(root:Path,bot_name:str,outer_manifest:dict,nested:dict):
    current=outer_manifest.get("lifecycle") or {}
    if current.get("auto_start") or current.get("auto_restart"):
        return {"auto_start":bool(current.get("auto_start")),"auto_restart":bool(current.get("auto_restart")),
                "source":"outer_manifest_positive_policy"}
    fv=read_json(root/"diagnostics"/"full_validation.json")
    if fv.get("critical_tests_ok") is True:
        for row in fv.get("supervisor_actions") or []:
            if str(row.get("service"))==bot_name:
                p=row.get("policy") or {}
                if p.get("auto_start") or p.get("auto_restart"):
                    return {"auto_start":bool(p.get("auto_start")),"auto_restart":bool(p.get("auto_restart")),
                            "source":"last_validated_full_validation"}
    p=nested.get("lifecycle") or {}
    if p.get("auto_start") or p.get("auto_restart"):
        return {"auto_start":bool(p.get("auto_start")),"auto_restart":bool(p.get("auto_restart")),
                "source":"nested_canonical_manifest"}
    return {"auto_start":False,"auto_restart":False,"source":"no_positive_managed_policy"}

def shim_text(bot_root:Path,target:Path):
    rel=target.relative_to(bot_root).as_posix()
    return '''# {marker}
from pathlib import Path
import os, runpy, sys

BOT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BOT_ROOT.parent.parent
TARGET = (BOT_ROOT / {rel!r}).resolve()

def main():
    if not TARGET.is_file():
        raise RuntimeError(f"Canonical runtime target missing: {{TARGET}}")
    runtime = TARGET.parent
    os.chdir(runtime)
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(runtime))
    runpy.run_path(str(TARGET), run_name="__main__")

if __name__ == "__main__":
    main()
'''.format(marker=MARKER, rel=rel)

def prepare_one(root:Path,bot_name:str,backup_dir:Path|None,apply:bool):
    bot=root/"bots"/bot_name
    nested=discover_nested(root,bot_name)
    if not nested.get("ok"):return nested
    selected=nested["selected"];target=Path(selected["entrypoint_abs"])
    outer_manifest=bot/"BOT_MANIFEST.json";outer_before=read_json(outer_manifest)
    policy=validated_policy(root,bot_name,outer_before,selected)
    root_main=bot/"main.py";existing=None
    if root_main.is_file():
        existing=root_main.read_text(encoding="utf-8-sig",errors="ignore")
        if MARKER not in existing:
            shim_needed=False
        else:
            shim_needed=True
    else:
        shim_needed=True
    after=dict(outer_before)
    after["name"]=bot_name;after["classification"]="CANONICAL"
    after["entrypoint"]="main.py";after["entrypoint_confidence"]="high"
    lifecycle=dict(after.get("lifecycle") or {})
    lifecycle["auto_start"]=policy["auto_start"];lifecycle["auto_restart"]=policy["auto_restart"]
    after["lifecycle"]=lifecycle
    after["runtime_bridge"]={
        "version":"3.0.7","canonical_target":str(target),"canonical_runtime_dir":str(target.parent),
        "policy_source":policy["source"],"updated_at_utc":utcnow(),
    }
    shim_body=shim_text(bot,target) if shim_needed else None
    if shim_body is not None:
        try:
            compile(shim_body,str(root_main),"exec")
        except Exception as exc:
            return {"ok":False,"bot":bot_name,"reason":f"generated_shim_compile_{type(exc).__name__}"}
    changed_shim=bool(shim_needed and (not root_main.is_file() or existing!=shim_body))
    changed_manifest=after!=outer_before
    backups=[]
    if apply:
        if backup_dir:
            if outer_manifest.is_file():
                b=backup_dir/"runtime_bridge"/bot_name/"BOT_MANIFEST.json";b.parent.mkdir(parents=True,exist_ok=True)
                b.write_bytes(outer_manifest.read_bytes());backups.append(str(b))
            if root_main.is_file() and changed_shim:
                b=backup_dir/"runtime_bridge"/bot_name/"main.py";b.parent.mkdir(parents=True,exist_ok=True)
                b.write_bytes(root_main.read_bytes());backups.append(str(b))
        if changed_shim:root_main.write_text(shim_body,encoding="utf-8")
        if changed_manifest:write_json(outer_manifest,after)
    return {
        "ok":True,"bot":bot_name,"nested":selected,"root_main":str(root_main),
        "root_main_existed":root_main.is_file(),
        "outer_manifest_existed":outer_manifest.is_file(),
        "root_main_existing_non_bridge":bool(existing and MARKER not in existing),
        "shim_needed":shim_needed,"changed_shim":changed_shim,"changed_manifest":changed_manifest,
        "policy":policy,"desired_running":bool(policy["auto_start"]),
        "backups":backups,"outer_before":outer_before,"outer_after":after,
    }

def process_alive(pid):
    try:
        pid=int(pid)
        if pid<=0:return False
        if os.name=="nt":
            r=subprocess.run(["tasklist","/FI",f"PID eq {pid}","/NH"],capture_output=True,text=True,timeout=10)
            return r.returncode==0 and str(pid) in r.stdout
        os.kill(pid,0);return True
    except Exception:return False

def pid_file(root:Path,bot_name:str):
    return root/"state"/"runtime_bridge"/f"{bot_name}.pid"

def process_command_matches(path:Path):
    if os.name!="nt":return []
    needle=str(path).replace("'","''")
    ps=("$p=Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
        f"$_.CommandLine -like '*{needle}*' }} | Select-Object ProcessId,Name,CommandLine; "
        "$p | ConvertTo-Json -Compress")
    try:
        r=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],
                         capture_output=True,text=True,timeout=15)
        raw=r.stdout.strip()
        if not raw:return []
        data=json.loads(raw)
        if isinstance(data,dict):data=[data]
        return data if isinstance(data,list) else []
    except Exception:return []

def runtime_status(root:Path,row:dict):
    bot=row["bot"];root_main=Path(row["root_main"]);target=Path(row["nested"]["entrypoint_abs"])
    pf=pid_file(root,bot);pid=None
    if pf.is_file():
        try:pid=int(pf.read_text(encoding="ascii").strip())
        except Exception:pid=None
    alive=bool(pid and process_alive(pid));matches=[]
    if not alive:
        matches=process_command_matches(root_main)+process_command_matches(target)
        matches=[x for x in matches if int(x.get("ProcessId") or 0)!=os.getpid()]
        if matches:alive=True;pid=int(matches[0]["ProcessId"])
    return {"alive":alive,"pid":pid,"matches":matches[:4]}

def direct_start(root:Path,row:dict):
    root_main=Path(row["root_main"]);bot_root=root_main.parent
    env=os.environ.copy();env["PYTHONPATH"]=str(root)+os.pathsep+env.get("PYTHONPATH","")
    logs=root/"logs";logs.mkdir(parents=True,exist_ok=True)
    outp=logs/f"{row['bot']}_runtime_bridge_stdout.log";errp=logs/f"{row['bot']}_runtime_bridge_stderr.log"
    out=outp.open("ab");err=errp.open("ab")
    flags=0
    if os.name=="nt":
        flags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)|getattr(subprocess,"DETACHED_PROCESS",0)
    try:
        proc=subprocess.Popen([sys.executable,str(root_main)],cwd=bot_root,env=env,
                              stdout=out,stderr=err,creationflags=flags,close_fds=(os.name!="nt"))
    finally:
        out.close();err.close()
    deadline=time.time()+8
    while time.time()<deadline:
        if proc.poll() is not None:
            tail=""
            try:tail=errp.read_text(encoding="utf-8",errors="replace")[-3000:]
            except Exception:pass
            return {"ok":False,"reason":"process_exited","returncode":proc.returncode,"stderr_tail":tail}
        time.sleep(.5)
    pid=proc.pid
    pf=pid_file(root,row["bot"]);pf.parent.mkdir(parents=True,exist_ok=True);pf.write_text(str(pid),encoding="ascii")
    # Ownership is intentionally transferred to the detached runtime bridge. Mark the
    # local Popen handle as released so Python does not emit ResourceWarning on GC.
    proc.returncode=0
    return {"ok":True,"pid":pid,"method":"runtime_bridge","stdout":str(outp),"stderr":str(errp)}

def ensure_one(root:Path,row:dict):
    st=runtime_status(root,row);desired=bool(row.get("desired_running"))
    if not desired:
        return {"ok":True,"bot":row["bot"],"desired_running":False,"action":"preserve_stopped_policy","status":st}
    if st["alive"]:
        return {"ok":True,"bot":row["bot"],"desired_running":True,"action":"already_running","status":st}
    vmcore=None
    try:
        sys.path.insert(0,str(root))
        from shared.vm_core.services import restart_service
        vmcore=restart_service(row["bot"],root,dry_run=False,background=True)
    except Exception as exc:
        vmcore={"ok":False,"error":f"{type(exc).__name__}:{exc}"}
    time.sleep(2);st2=runtime_status(root,row)
    if st2["alive"]:
        return {"ok":True,"bot":row["bot"],"desired_running":True,"action":"vm_core","vm_core":vmcore,"status":st2}
    direct=direct_start(root,row);st3=runtime_status(root,row)
    return {"ok":bool(direct.get("ok") and st3["alive"]),"bot":row["bot"],"desired_running":True,
            "action":"direct_bridge" if direct.get("ok") else "failed","vm_core":vmcore,"direct":direct,"status":st3}

def prepare(root:Path,backup_dir:Path|None,apply:bool,bots):
    previews=[prepare_one(root,b,backup_dir,False) for b in bots]
    ok=all(x.get("ok") for x in previews)
    if not ok or not apply:
        return {"schema_version":1,"version":"3.0.7","generated_at_utc":utcnow(),"root":str(root),
                "prepared":False,"ok":ok,"services":previews}
    rows=[]
    try:
        for b in bots:
            row=prepare_one(root,b,backup_dir,True)
            rows.append(row)
            if not row.get("ok"):
                raise RuntimeError(f"bridge_apply_failed:{b}:{row.get('reason')}")
    except Exception as exc:
        # Restore only paths this bridge may have changed.
        for row in reversed(rows):
            bot=root/"bots"/str(row.get("bot"))
            backup_base=(backup_dir/"runtime_bridge"/str(row.get("bot"))) if backup_dir else None
            manifest=bot/"BOT_MANIFEST.json";main=bot/"main.py"
            if backup_base and (backup_base/"BOT_MANIFEST.json").is_file():
                manifest.write_bytes((backup_base/"BOT_MANIFEST.json").read_bytes())
            elif not row.get("outer_manifest_existed"):
                manifest.unlink(missing_ok=True)
            if backup_base and (backup_base/"main.py").is_file():
                main.write_bytes((backup_base/"main.py").read_bytes())
            elif not row.get("root_main_existed") and row.get("changed_shim"):
                main.unlink(missing_ok=True)
        return {"schema_version":1,"version":"3.0.7","generated_at_utc":utcnow(),"root":str(root),
                "prepared":False,"ok":False,"reason":f"{type(exc).__name__}:{exc}","services":rows or previews}
    state={"schema_version":1,"version":"3.0.7","generated_at_utc":utcnow(),"root":str(root),
           "prepared":True,"ok":True,"services":rows}
    write_json(root/"state"/"runtime_bridge.json",state)
    return state

def ensure(root:Path,state:dict):
    rows=[ensure_one(root,row) for row in state.get("services") or [] if row.get("ok")]
    out={"schema_version":1,"version":"3.0.7","generated_at_utc":utcnow(),
         "ok":all(x.get("ok") for x in rows),"services":rows}
    write_json(root/"diagnostics"/"runtime_bridge_status.json",out)
    return out

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True);p.add_argument("--backup-dir")
    p.add_argument("--report",required=True);p.add_argument("--mode",choices=["prepare","ensure","status"],required=True)
    p.add_argument("--apply",action="store_true");p.add_argument("--bots",nargs="+",default=list(MANAGED))
    a=p.parse_args(argv);root=Path(a.root).resolve();report=Path(a.report)
    backup=Path(a.backup_dir).resolve() if a.backup_dir else None
    if a.mode=="prepare":
        out=prepare(root,backup,a.apply,a.bots);write_json(report,out)
    else:
        state=read_json(root/"state"/"runtime_bridge.json")
        if not state.get("services"):
            out={"ok":False,"reason":"runtime_bridge_state_missing"}
        elif a.mode=="ensure":
            out=ensure(root,state)
        else:
            rows=[{"bot":row["bot"],"desired_running":row.get("desired_running"),"status":runtime_status(root,row)}
                  for row in state["services"]]
            out={"ok":True,"services":rows}
        write_json(report,out)
    summary={"ok":out.get("ok"),"mode":a.mode,"report":str(report),
             "services":[{"bot":x.get("bot"),"desired_running":x.get("desired_running"),
                          "action":x.get("action"),"alive":(x.get("status") or {}).get("alive")}
                         for x in out.get("services",[])]}
    print(json.dumps(summary,default=str))
    return 0 if out.get("ok") else 4

if __name__=="__main__":
    raise SystemExit(main())
