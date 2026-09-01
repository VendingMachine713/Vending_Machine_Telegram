from __future__ import annotations
from pathlib import Path
import json


def _env_bool(path,name):
    if not path.is_file(): return None
    try:
        for raw in path.read_text(encoding="utf-8-sig",errors="ignore").splitlines():
            line=raw.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k,v=line.split("=",1)
            if k.strip()==name: return v.strip().strip('"').strip("'").lower() in {"1","true","yes","on"}
    except Exception: pass
    return None

def _env_present(path,name):
    if not path.is_file(): return False
    try:
        for raw in path.read_text(encoding="utf-8-sig",errors="ignore").splitlines():
            line=raw.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k,v=line.split("=",1)
            if k.strip()==name: return bool(v.strip().strip('"').strip("'"))
    except Exception: pass
    return False

class SecurityPostureEngine:
    def __init__(self,root): self.root=Path(root)

    def evaluate(self, integrated=None):
        bot=self.root/"bots"/"Admin_Command_Centre"
        if not bot.exists():
            return {"score":80,"admin_token_configured":None,"admin_count":None,
                    "lifecycle_mutations_enabled":None,"high_severity_alerts":0,
                    "applicable":False,"findings":["Admin Command Centre is not present in this test/project context; administrative security posture is not applicable."]}
        envs=[bot/".env",*sorted(bot.glob("**/.env"),key=lambda p:len(p.parts))]
        token=any(_env_present(p,"VM_ADMIN_BOT_TOKEN") for p in envs)
        mutations=next((x for x in (_env_bool(p,"VM_ADMIN_ALLOW_MUTATIONS") for p in envs) if x is not None),False)
        admin_count=0
        try:
            from shared.vm_core.admins import load_admin_ids
            admin_count=len(load_admin_ids(self.root))
        except Exception: pass
        high_alerts=0
        for a in ((integrated or {}).get("VM_Platform",{}).get("evidence",{}).get("open_alerts",[]) or []):
            if str(a.get("severity","WARN")).lower() in {"critical","crit","error","high"}: high_alerts+=1
        score=100; findings=[]
        if not token:
            score-=25; findings.append("Admin bot token was not detected in the canonical local environment.")
        if admin_count<=0:
            score-=35; findings.append("No persisted Admin Command Centre administrator was detected.")
        if mutations:
            score-=5; findings.append("Lifecycle mutations are enabled and require confirmation controls.")
        if high_alerts:
            score-=min(25,high_alerts*10); findings.append(f"{high_alerts} high-severity VM Guard alerts are open.")
        return {"score":max(0,score),"admin_token_configured":token,"admin_count":admin_count,
                "lifecycle_mutations_enabled":bool(mutations),"high_severity_alerts":high_alerts,
                "findings":findings}
