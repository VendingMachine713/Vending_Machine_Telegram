from __future__ import annotations
import argparse, importlib.util, json, os, subprocess, sys, time
from pathlib import Path

def load_repair_tool(package_root:Path):
    p=package_root/"tools"/"Intelligence"/"REPAIR_RUNTIME_MANIFESTS.py"
    spec=importlib.util.spec_from_file_location("vm_runtime_manifest_repair",p)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    return mod

def pid_alive(pid):
    try:
        pid=int(pid)
        if pid<=0:return False
        if os.name=="nt":
            r=subprocess.run(["tasklist","/FI",f"PID eq {pid}","/NH"],capture_output=True,text=True,timeout=10)
            return r.returncode==0 and str(pid) in r.stdout
        os.kill(pid,0);return True
    except Exception:
        return False


def find_matching_windows_process(selected):
    if os.name!="nt":
        return None
    entry=str(Path(selected["entrypoint_abs"]).resolve()).lower()
    runtime=str(Path(selected["runtime_dir"]).resolve()).lower()
    script=(
        "$rows=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object {$_.CommandLine}; "
        "$rows | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        r=subprocess.run(["powershell.exe","-NoProfile","-Command",script],
                         capture_output=True,text=True,timeout=15)
        if r.returncode!=0 or not r.stdout.strip():
            return None
        data=json.loads(r.stdout)
        if isinstance(data,dict):data=[data]
        for row in data or []:
            cmd=str(row.get("CommandLine") or "").lower()
            if entry in cmd or (runtime in cmd and Path(entry).name.lower() in cmd):
                pid=row.get("ProcessId")
                if pid and pid_alive(pid):
                    return int(pid)
    except Exception:
        return None
    return None

def service_row(root:Path,bot:str):
    sys.path.insert(0,str(root))
    try:
        from shared.vm_core.services import service_status
        rows=service_status(root)
        return next((x for x in rows if str(x.get("name"))==bot),None)
    except Exception:
        return None

def status(root:Path,package_root:Path,bot:str):
    repair=load_repair_tool(package_root)
    discovered=repair.discover_runtime(root,bot)
    row=service_row(root,bot)
    return {
        "ok":bool(discovered.get("ok")),
        "bot":bot,
        "selected":discovered.get("selected"),
        "service_status":row,
        "process_alive":bool((row or {}).get("process_alive")),
    }

def direct_start(root:Path,selected:dict,bot:str):
    entry=Path(selected["entrypoint_abs"]);runtime=Path(selected["runtime_dir"])
    if not entry.is_file():
        return {"ok":False,"reason":"validated_entrypoint_missing","entrypoint":str(entry)}
    env=os.environ.copy()
    env["PYTHONPATH"]=str(root)+os.pathsep+env.get("PYTHONPATH","")
    logs=root/"logs";logs.mkdir(parents=True,exist_ok=True)
    out_path=logs/"admin_command_centre_intelligence_stdout.log"
    err_path=logs/"admin_command_centre_intelligence_stderr.log"
    out=out_path.open("ab");err=err_path.open("ab")
    flags=0
    if os.name=="nt":
        flags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)|getattr(subprocess,"DETACHED_PROCESS",0)
    try:
        proc=subprocess.Popen([sys.executable,str(entry)],cwd=runtime,env=env,stdout=out,stderr=err,
                              creationflags=flags,close_fds=(os.name!="nt"))
    except Exception as exc:
        out.close();err.close()
        return {"ok":False,"reason":f"direct_start_{type(exc).__name__}","error":str(exc)}
    finally:
        try:out.close()
        except Exception:pass
        try:err.close()
        except Exception:pass
    deadline=time.time()+8
    while time.time()<deadline:
        if proc.poll() is not None:
            tail=""
            try:tail=err_path.read_text(encoding="utf-8",errors="replace")[-2500:]
            except Exception:pass
            return {"ok":False,"reason":"direct_process_exited","returncode":proc.returncode,"stderr_tail":tail}
        time.sleep(.5)
    pid=proc.pid
    pid_dir=root/"state"/"pids";pid_dir.mkdir(parents=True,exist_ok=True)
    (pid_dir/f"{bot}.pid").write_text(str(pid),encoding="ascii")
    # The tool intentionally leaves the bot running after it exits. Close/detach our
    # process handle so strict ResourceWarning qualification does not flag that design.
    if os.name=="nt":
        try:proc._handle.Close()
        except Exception:pass
    proc.returncode=0
    return {"ok":True,"method":"direct_canonical_entrypoint","pid":pid,"entrypoint":str(entry),
            "runtime_dir":str(runtime),"stdout":str(out_path),"stderr":str(err_path)}

def ensure(root:Path,package_root:Path,bot:str,should_run:bool):
    st=status(root,package_root,bot)
    if not st["ok"]:
        return {"ok":False,"reason":"no_validated_runtime","status":st}
    if not should_run:
        return {"ok":True,"method":"preserve_stopped_policy","status":st}
    selected=st["selected"]
    sys.path.insert(0,str(root))
    restart=None
    try:
        from shared.vm_core.services import restart_service
        restart=restart_service(bot,root,dry_run=False,background=True)
    except Exception as exc:
        restart={"ok":False,"error":f"{type(exc).__name__}:{exc}"}
    # VM Core may provide a PID even when its status cache has not refreshed yet.
    start=(restart or {}).get("start") if isinstance(restart,dict) else None
    pid=(start or {}).get("pid") if isinstance(start,dict) else None
    deadline=time.time()+8
    while time.time()<deadline:
        row=service_row(root,bot)
        if row and row.get("process_alive"):
            return {"ok":True,"method":"vm_core","restart":restart,"status":row}
        if pid and pid_alive(pid):
            return {"ok":True,"method":"vm_core_pid","restart":restart,"pid":pid}
        time.sleep(.5)
    # Avoid a duplicate if VM Core started the process but its status cache lagged.
    matched=find_matching_windows_process(selected)
    if matched:
        return {"ok":True,"method":"vm_core_process_scan","restart":restart,"pid":matched}
    # Fail over only after VM Core demonstrably failed to establish a live process.
    direct=direct_start(root,selected,bot)
    return {"ok":bool(direct.get("ok")),"method":"direct_fallback" if direct.get("ok") else "failed",
            "restart":restart,"direct":direct,"status_before":st}

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True);p.add_argument("--package-root",required=True)
    p.add_argument("--bot",default="Admin_Command_Centre")
    p.add_argument("--action",choices=["status","ensure"],required=True)
    p.add_argument("--should-run",default="true")
    p.add_argument("--report")
    a=p.parse_args(argv)
    root=Path(a.root).resolve();package=Path(a.package_root).resolve()
    if a.action=="status":
        result=status(root,package,a.bot)
    else:
        should=str(a.should_run).lower() in {"1","true","yes","on"}
        result=ensure(root,package,a.bot,should)
    if a.report:
        rp=Path(a.report);rp.parent.mkdir(parents=True,exist_ok=True)
        rp.write_text(json.dumps(result,indent=2,default=str)+"\n",encoding="utf-8")
    print(json.dumps(result,default=str))
    return 0 if result.get("ok") else 4

if __name__=="__main__":
    raise SystemExit(main())
