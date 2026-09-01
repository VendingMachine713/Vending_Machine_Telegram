from __future__ import annotations
from pathlib import Path
import json
from typing import Any, Callable
from .paths import project_root
from .db import PlatformDB, utcnow
from .registry import sync_accounts, sync_destinations
from .health import run_health
from .logging_setup import log_event

def enqueue(job_type: str, payload: dict[str,Any] | None = None, root: Path | None = None) -> int:
    db=PlatformDB(root=root or project_root()); db.init()
    jid=db.add_job(job_type,payload)
    log_event("job_enqueued",data={"job_id":jid,"job_type":job_type},root=root or project_root())
    return jid

def run_one(root: Path | None = None) -> dict[str,Any]:
    root=root or project_root()
    db=PlatformDB(root=root); db.init()
    with db.connect() as con:
        row=con.execute("SELECT * FROM jobs WHERE status IN ('QUEUED','RETRYING') ORDER BY id LIMIT 1").fetchone()
        if not row:
            return {"ok":True,"message":"No queued jobs."}
        job=dict(row)
        con.execute("UPDATE jobs SET status='RUNNING',attempts=attempts+1,updated_at_utc=? WHERE id=?",(utcnow(),job["id"]))
    try:
        payload=json.loads(job["payload_json"] or "{}")
        jt=job["job_type"]
        if jt=="SYNC_ACCOUNTS":
            result={"accounts_synced":sync_accounts(root)}
        elif jt=="SYNC_DESTINATIONS":
            result=sync_destinations(root)
        elif jt=="HEALTH_CHECK":
            result={"services":run_health(root)}
        elif jt.startswith("SIM_"):
            result={"simulated":True,"payload":payload}
        else:
            raise ValueError(f"Unknown job type: {jt}")
        with db.connect() as con:
            con.execute("UPDATE jobs SET status='COMPLETED',last_error=NULL,updated_at_utc=? WHERE id=?",(utcnow(),job["id"]))
        log_event("job_completed",data={"job_id":job["id"],"job_type":jt},root=root)
        return {"ok":True,"job_id":job["id"],"result":result}
    except Exception as e:
        with db.connect() as con:
            current=con.execute("SELECT attempts,max_attempts FROM jobs WHERE id=?",(job["id"],)).fetchone()
            status="RETRYING" if current and current["attempts"] < current["max_attempts"] else "FAILED"
            con.execute("UPDATE jobs SET status=?,last_error=?,updated_at_utc=? WHERE id=?",(status,str(e),utcnow(),job["id"]))
        log_event("job_failed",level="ERROR",data={"job_id":job["id"],"error":str(e)},root=root)
        return {"ok":False,"job_id":job["id"],"error":str(e)}
