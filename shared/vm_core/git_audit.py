from __future__ import annotations
from pathlib import Path
import shutil
import subprocess
from typing import Any
from .paths import project_root

SENSITIVE_NAMES={".env","secrets.json","credentials.json","config.env"}
SENSITIVE_SUFFIXES={".session",".session-journal",".key",".pem"}
RUNTIME_SUFFIXES={".db",".sqlite",".sqlite3",".log"}
RUNTIME_PARTS={"logs","backups","diagnostics","state","media_cache","downloads"}

def audit(root:Path|None=None)->dict[str,Any]:
    root=root or project_root()
    git=shutil.which("git")
    if not git:
        return {"available":False,"ok":True,"tracked":[],"findings":[]}
    inside=subprocess.run([git,"rev-parse","--is-inside-work-tree"],cwd=root,text=True,capture_output=True)
    if inside.returncode!=0:
        return {"available":True,"repository":False,"ok":True,"tracked":[],"findings":[]}
    r=subprocess.run([git,"ls-files","-z"],cwd=root,capture_output=True)
    tracked=[x.decode("utf-8","replace") for x in r.stdout.split(b"\0") if x]
    findings=[]
    for rel in tracked:
        p=Path(rel)
        low_parts={part.lower() for part in p.parts}
        name=p.name.lower()
        suffix=p.suffix.lower()
        if name in SENSITIVE_NAMES or suffix in SENSITIVE_SUFFIXES:
            findings.append({"path":rel,"severity":"CRITICAL","reason":"sensitive credential/session file is tracked"})
        elif suffix in RUNTIME_SUFFIXES or (low_parts & RUNTIME_PARTS):
            findings.append({"path":rel,"severity":"WARN","reason":"runtime/generated data is tracked"})
    return {
        "available":True,"repository":True,"ok":not any(f["severity"]=="CRITICAL" for f in findings),
        "tracked_count":len(tracked),"findings":findings,
    }
