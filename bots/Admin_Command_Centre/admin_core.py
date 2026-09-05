from __future__ import annotations
from pathlib import Path
import json,os,sys
from typing import Any
BOT_DIR=Path(__file__).resolve().parent; ROOT=BOT_DIR.parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from shared.vm_core.services import service_status,start_service,stop_service,restart_service,run_service_cli
from shared.vm_core.health import run_health
from shared.vm_core.registry import registry_summary
from shared.vm_core.db import PlatformDB
from shared.vm_core.backup import create_backup
from shared.vm_core.doctor import run_doctor
from shared.vm_core.support import create_support_bundle
from shared.vm_core.supervisor import supervise_once
from shared.vm_core.intelligence import intelligence_summary,format_intelligence_summary
from shared.vm_core.autoposter_progress import smart_auto_poster_progress
from shared.vm_core.progress import format_progress
from shared.vm_core.progress_registry import format_all_progress
from shared.vm_core.admin_exceptions import admin_exceptions,format_admin_exceptions
from shared.vm_core.incident_runtime import incident_timeline
from shared.vm_core.autoposter_recovery import recovery_preview, format_recovery_preview
from shared.vm_core.canonical_recommendations import canonical_recommendation_summary
from shared.vm_core.canonical_review_audit import canonical_review_audit_summary
from shared.vm_core.canonical_review_feedback import (
    CanonicalReviewFeedbackError,
    transition_canonical_review,
)
MUTATING={'backup','support','start','stop','restart','supervise','poster_start','poster_stop','poster_restart'}
POSTER_SERVICE='Smart_Auto_Poster_V2'

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

def help_text(cfg):
    return (
        'VM ADMIN COMMAND CENTRE\n\n'
        '/vm\n/status\n/health\n/progress\n/intelligence\n/brain\n/registry\n/jobs\n/doctor\n/exceptions\n/incidents\n/backup\n/support\n'
        '/start <service>\n/stop <service>\n/restart <service>\n/supervise\n\n'
        'SMART AUTO POSTER\n'
        '/poster\n/poster_status\n/poster_progress\n/poster_health\n/poster_queue\n/poster_campaigns\n/poster_recovery_preview\n'
        '/poster_start\n/poster_stop\n/poster_restart\n\n'
        'GOVERNED REVIEW\n'
        '/review - list canonical recommendations awaiting review\n'
        '/review_audit - read-only recommendation lifecycle audit\n'
        '/review_accept <key> [note] - explicitly approve metadata only\n'
        '/review_dismiss <key> [note] - dismiss a recommendation\n\n'
        'Mutating commands: '+('ENABLED' if cfg['allow_mutations'] else 'DISABLED')
    )

def _poster_service_row()->dict[str,Any]|None:
    for row in service_status(ROOT):
        if str(row.get('name','')).lower()==POSTER_SERVICE.lower():
            return row
    return None

def _poster_status_text()->str:
    row=_poster_service_row()
    if not row: return 'SMART AUTO POSTER\nService not found in VM registry.'
    status='RUNNING' if row.get('process_alive') else row.get('runtime_status','UNKNOWN')
    pid=row.get('pid') or '-'
    return f'SMART AUTO POSTER\nStatus: {status}\nPID: {pid}\nService: {POSTER_SERVICE}'

def _poster_progress_text()->str:
    try:
        return format_progress(smart_auto_poster_progress(ROOT))[:3900]
    except Exception as exc:
        return f'SMART AUTO POSTER - UNIVERSAL PROGRESS\nProgress unavailable: {type(exc).__name__}: {exc}'[:3900]

def _platform_progress_text()->str:
    try:
        return format_all_progress(ROOT)[:3900]
    except Exception as exc:
        return f'UNIVERSAL PROGRESS ENGINE\nProgress unavailable: {type(exc).__name__}: {exc}'[:3900]

def _poster_cli(command:str)->str:
    allowed={
        'status':['status'],
        'health':['health'],
        'queue':['queue-capacity'],
        'campaigns':['campaigns'],
    }
    args=allowed.get(command)
    if not args: return 'Unsupported Smart Auto Poster command.'
    result=run_service_cli(POSTER_SERVICE,args,ROOT,timeout=30)
    output=(result.get('stdout') or '').strip()
    error=(result.get('stderr') or '').strip()
    if result.get('ok'):
        return output[:3900] or f'Smart Auto Poster {command}: OK'
    detail=error or output or result.get('error') or result.get('reason') or 'Unknown error'
    return f'Smart Auto Poster {command} failed.\n{detail}'[:3900]

def _poster_help(cfg)->str:
    return (
        'SMART AUTO POSTER CONTROL\n\n'
        '/poster_status - VM runtime state\n'
        '/poster_progress - live universal progress view\n'
        '/poster_health - poster health command\n'
        '/poster_queue - queue capacity/status\n'
        '/poster_campaigns - campaign list\n'
        '/poster_start - start poster service\n'
        '/poster_stop - stop poster service\n'
        '/poster_restart - restart poster service\n\n'
        'Service mutations: '+('ENABLED' if cfg['allow_mutations'] else 'DISABLED')
    )

def _review_text()->str:
    summary=canonical_recommendation_summary(root=ROOT,limit=50)
    rows=[row for row in summary.get('recommendations',[]) if str(row.get('status','')).upper() in {'PROPOSED','ACCEPTED'}]
    lines=['GOVERNED REVIEW','Operator approval is required; No Telegram action is executed.']
    if not rows: return '\n'.join(lines+['No actionable canonical recommendations.'])
    for row in rows[:10]:
        key=str(row.get('recommendation_key') or '')
        action=str(row.get('action') or 'review')
        rationale=' '.join(str(row.get('rationale') or '').split())[:180]
        lines.append(f"\n{key}\nStatus: {str(row.get('status') or 'UNKNOWN').upper()} | Priority: {float(row.get('priority') or 0):.2f} | Confidence: {float(row.get('confidence') or 0):.2f}\nAction: {action}\nRationale: {rationale}")
    if len(rows)>10: lines.append(f'\n…and {len(rows)-10} more. Use the canonical key with /review_accept or /review_dismiss.')
    return '\n'.join(lines)[:3900]

def _review_audit_text()->str:
    summary=canonical_review_audit_summary(root=ROOT,limit=20)
    stages=', '.join(f'{key}={value}' for key,value in summary.get('stage_counts',{}).items()) or 'none'
    return (f"GOVERNED REVIEW AUDIT\nStatus: {summary.get('status','UNAVAILABLE')} | Timelines: {summary.get('count',0)}\n"
            f"Stages: {stages}\nMalformed rows: {summary.get('malformed_rows',0)} | Duplicate events ignored: {summary.get('duplicate_events_ignored',0)}\n"
            'Read-only projection; operator review required; automatic acceptance and execution are disabled.')[:3900]

def _review_transition(user_id:int, cmd:str, args:list[str])->str:
    if not args: return f'Usage: /{cmd} <recommendation_key> [note]'
    key=args[0].strip()
    note=' '.join(args[1:]).strip() or None
    target='ACCEPTED' if cmd=='review_accept' else 'DISMISSED'
    try:
        decision=transition_canonical_review(key,target,actor=f'telegram:{user_id}',note=note,root=ROOT)
    except CanonicalReviewFeedbackError as exc:
        return f'REVIEW {target} BLOCKED\n{exc}'[:3900]
    return (f"REVIEW {decision.status}\nKey: {decision.recommendation_key}\n"
            f"Previous: {decision.previous_status}\nActor: {decision.actor}\nAudit event: {decision.event_id}\n"
            'No Telegram action was executed; this changed recommendation metadata only.')[:3900]

def handle_command(user_id:int,text:str,cfg:dict[str,Any]|None=None)->str:
    cfg=cfg or config()
    if not is_admin(user_id,cfg): return 'Access denied.'
    cmd,args=parse_command(text)
    if cmd in {'vm','help',''}: return help_text(cfg)
    if cmd=='progress': return _platform_progress_text()
    if cmd=='poster': return _poster_help(cfg)
    if cmd=='poster_status': return _poster_status_text()
    if cmd=='poster_progress': return _poster_progress_text()
    if cmd=='poster_recovery_preview':
        try: return format_recovery_preview(recovery_preview(ROOT))[:3900]
        except Exception as exc: return f'SMART AUTO POSTER RECOVERY PREVIEW\nUnavailable: {type(exc).__name__}'
    if cmd=='poster_health': return _poster_cli('health')
    if cmd=='poster_queue': return _poster_cli('queue')
    if cmd=='poster_campaigns': return _poster_cli('campaigns')
    if cmd in {'review','recommendations'}: return _review_text()
    if cmd=='review_audit': return _review_audit_text()
    if cmd in {'review_accept','review_dismiss'}: return _review_transition(user_id,cmd,args)
    if cmd=='status': return 'VM SERVICES\n'+'\n'.join(f"{('RUNNING' if r.get('process_alive') else r.get('runtime_status','UNKNOWN')):<12} {r['name']}" for r in service_status(ROOT))
    if cmd=='health': return 'VM HEALTH\n'+'\n'.join(f"{r['status']:<15} {r['service']}" for r in run_health(ROOT))
    if cmd in {'intelligence','brain'}: return format_intelligence_summary(intelligence_summary(ROOT,refresh=True))[:3900]
    if cmd=='registry':
        r=registry_summary(ROOT); return f"VM REGISTRY\nDestinations: {r['destinations']}\nAccounts: {r['accounts']}"
    if cmd=='jobs':
        rows=PlatformDB(root=ROOT).jobs(10); return 'VM JOBS\n'+(('No recent jobs.') if not rows else '\n'.join(f"#{r['id']} {r['status']:<10} {r['job_type']}" for r in rows))
    if cmd=='doctor':
        s=run_doctor(ROOT)['summary']; return f"VM DOCTOR\nPASS: {s['PASS']}\nINFO: {s['INFO']}\nWARN: {s['WARN']}\nFAIL: {s['FAIL']}"
    if cmd=='exceptions': return format_admin_exceptions(admin_exceptions(ROOT))[:3900]
    if cmd=='incidents':
        rows=incident_timeline(ROOT,10)
        return 'VM INCIDENTS\n'+(('No incidents.') if not rows else '\n'.join(f"#{r['id']} {r['status']:<9} {r['severity']:<8} {r['incident_key']}" for r in rows))
    if cmd in MUTATING and not cfg['allow_mutations']: return 'Mutating commands are disabled. Set VM_ADMIN_ALLOW_MUTATIONS=true locally after reviewing safety.'
    if cmd=='backup': return 'Backup created:\n'+str(create_backup(ROOT))
    if cmd=='support': return 'Support bundle created:\n'+str(create_support_bundle(ROOT))
    if cmd in {'start','stop','restart'}:
        if not args: return f'Usage: /{cmd} <service>'
        name=' '.join(args); result=start_service(name,ROOT,dry_run=False) if cmd=='start' else stop_service(name,ROOT,dry_run=False) if cmd=='stop' else restart_service(name,ROOT,dry_run=False)
        return json.dumps(result,indent=2,default=str)[:3500]
    if cmd=='poster_start': return json.dumps(start_service(POSTER_SERVICE,ROOT,dry_run=False),indent=2,default=str)[:3500]
    if cmd=='poster_stop': return json.dumps(stop_service(POSTER_SERVICE,ROOT,dry_run=False),indent=2,default=str)[:3500]
    if cmd=='poster_restart': return json.dumps(restart_service(POSTER_SERVICE,ROOT,dry_run=False),indent=2,default=str)[:3500]
    if cmd=='supervise': return json.dumps(supervise_once(ROOT,apply=True),indent=2,default=str)[:3500]
    return help_text(cfg)
