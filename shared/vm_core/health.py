from __future__ import annotations
from pathlib import Path
import sqlite3
from typing import Any
from .paths import project_root
from .manifests import discover_bots
from .services import service_status
from .db import PlatformDB
from .runtime_requirements import runtime_configuration_status

def _db_check(path: Path) -> str:
    try:
        con=sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True,timeout=2)
        try:
            row=con.execute('PRAGMA integrity_check').fetchone(); return row[0] if row else 'no result'
        finally: con.close()
    except sqlite3.Error as e: return f'ERROR: {e}'

def run_health(root: Path|None=None)->list[dict[str,Any]]:
    root=root or project_root(); db=PlatformDB(root=root); db.init(); runtime={r['name']:r for r in service_status(root)}; out=[]
    for bot in discover_bots(root):
        cfg=runtime_configuration_status(Path(bot.path))
        details={'classification':bot.classification,'entrypoint':bot.entrypoint,'entrypoint_confidence':bot.entrypoint_confidence,'manifest':bot.manifest_present,'runtime_status':runtime.get(bot.folder,{}).get('runtime_status','UNKNOWN'),'process_alive':runtime.get(bot.folder,{}).get('process_alive',False),'configuration':cfg,'databases':{}}
        for rel in bot.databases[:20]: details['databases'][rel]=_db_check(Path(bot.path)/rel)
        bad=any(v!='ok' for v in details['databases'].values())
        if bot.classification=='PLACEHOLDER': status='PLANNED'
        elif not cfg['configured']: status='CONFIG_REQUIRED'
        elif bad: status='DEGRADED'
        elif not bot.entrypoint and not bot.launchers: status='DEGRADED'
        elif details['process_alive']: status='ALIVE'
        else: status='READY'
        db.set_health(bot.folder,status,details); out.append({'service':bot.folder,'status':status,'detail':details})
    return out
