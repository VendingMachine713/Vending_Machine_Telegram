from __future__ import annotations
from pathlib import Path
import json,os,sys
from typing import Any
BOT_DIR=Path(__file__).resolve().parent; ROOT=BOT_DIR.parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from shared.vm_core.services import service_status,start_service,stop_service,restart_service
from shared.vm_core.health import run_health
from shared.vm_core.registry import registry_summary
from shared.vm_core.db import PlatformDB
from shared.vm_core.backup import create_backup
from shared.vm_core.doctor import run_doctor
from shared.vm_core.support import create_support_bundle
from shared.vm_core.supervisor import supervise_once
from shared.vm_core.intelligence import intelligence_summary,format_intelligence_summary
MUTATING={'backup','support','start','stop','restart','supervise'}
def load_local_env(path:Path|None=None)->dict[str,str]:
    path=path or BOT_DIR/'.env'; data={}
    if not path.is_file(): return data
    for raw in path.read_text(encoding='utf-8',errors='ignore').splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k,v=line.split('=',1); data[k.strip()]=v.strip().strip('"').strip("'")
    return data
def set_local_env(name:str,value:str,path:Path|None=None)->None:
    path=path or BOT_DIR/'.env'; lines=path.read_text(encoding='utf-8',errors='ignore').splitlines() if path.is_file() else []; out=[]; found=False
    for raw in lines:
        if raw.strip().startswith(name+'='):
            out.append(name+'='+value); found=True
        else: out.append(raw)
    if not found: out.append(name+'='+value)
    path.write_text('\n'.join(out).rstrip()+'\n',encoding='utf-8')
def config()->dict[str,Any]:
    local=load_local_env(); get=lambda n,d='': os.getenv(n) or local.get(n,d); ids=set()
    for value in get('VM_ADMIN_USER_IDS').replace(';',',').split(','):
        try:
            if value.strip(): ids.add(int(value.strip()))
        except ValueError: pass
    return {'token':get('VM_ADMIN_BOT_TOKEN'),'admin_ids':ids,'allow_mutations':get('VM_ADMIN_ALLOW_MUTATIONS','false').lower() in {'1','true','yes','on'}}
def claim_admin(user_id:int)->None: set_local_env('VM_ADMIN_USER_IDS',str(user_id))
def is_admin(user_id:int,cfg:dict[str,Any])->bool: return user_id in cfg['admin_ids']
def parse_command(text:str):
    text=(text or '').strip()
    if not text.startswith('/'): return '',[]
    first,*rest=text.split(); return first[1:].split('@',1)[0].lower(),rest
def help_text(cfg): return 'VM ADMIN COMMAND CENTRE\n\n/vm\n/status\n/health\n/intelligence\n/brain\n/registry\n/jobs\n/doctor\n/backup\n/support\n/start <service>\n/stop <service>\n/restart <service>\n/supervise\n\nMutating commands: '+('ENABLED' if cfg['allow_mutations'] else 'DISABLED')
def handle_command(user_id:int,text:str,cfg:dict[str,Any]|None=None)->str:
    cfg=cfg or config()
    if not is_admin(user_id,cfg): return 'Access denied.'
    cmd,args=parse_command(text)
    if cmd in {'vm','help',''}: return help_text(cfg)
    if cmd=='status': return 'VM SERVICES\n'+'\n'.join(f"{('RUNNING' if r.get('process_alive') else r.get('runtime_status','UNKNOWN')):<12} {r['name']}" for r in service_status(ROOT))
    if cmd=='health': return 'VM HEALTH\n'+'\n'.join(f"{r['status']:<15} {r['service']}" for r in run_health(ROOT))
    if cmd in {'intelligence','brain'}: return format_intelligence_summary(intelligence_summary(ROOT,refresh=True))[:3900]
    if cmd=='registry':
        r=registry_summary(ROOT); return f"VM REGISTRY\nDestinations: {r['destinations']}\nAccounts: {r['accounts']}"
    if cmd=='jobs':
        rows=PlatformDB(root=ROOT).jobs(10); return 'VM JOBS\n'+(('No recent jobs.') if not rows else '\n'.join(f"#{r['id']} {r['status']:<10} {r['job_type']}" for r in rows))
    if cmd=='doctor':
        s=run_doctor(ROOT)['summary']; return f"VM DOCTOR\nPASS: {s['PASS']}\nINFO: {s['INFO']}\nWARN: {s['WARN']}\nFAIL: {s['FAIL']}"
    if cmd in MUTATING and not cfg['allow_mutations']: return 'Mutating commands are disabled. Set VM_ADMIN_ALLOW_MUTATIONS=true locally after reviewing safety.'
    if cmd=='backup': return 'Backup created:\n'+str(create_backup(ROOT))
    if cmd=='support': return 'Support bundle created:\n'+str(create_support_bundle(ROOT))
    if cmd in {'start','stop','restart'}:
        if not args: return f'Usage: /{cmd} <service>'
        name=' '.join(args); result=start_service(name,ROOT,dry_run=False) if cmd=='start' else stop_service(name,ROOT,dry_run=False) if cmd=='stop' else restart_service(name,ROOT,dry_run=False)
        return json.dumps(result,indent=2,default=str)[:3500]
    if cmd=='supervise': return json.dumps(supervise_once(ROOT,apply=True),indent=2,default=str)[:3500]
    return help_text(cfg)
