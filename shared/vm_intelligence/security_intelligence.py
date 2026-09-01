from __future__ import annotations
from pathlib import Path
import hashlib,re

TOKEN_PATTERNS=[
    re.compile(rb'\b\d{6,12}:[A-Za-z0-9_-]{25,}\b'),
    re.compile(rb'(?i)(?:api[_-]?hash|password|secret)\s*[:=]\s*["\'][^"\']{12,}["\']'),
]

class SecurityBrain:
    """Detects exposure indicators without persisting secret values."""
    def __init__(self,root):self.root=Path(root)

    def analyze(self, integrated):
        findings=[];scanned=0;secret_hits=[]
        bots=self.root/"bots"
        if bots.exists():
            for p in bots.rglob("*"):
                if not p.is_file() or p.suffix.lower() not in {".py",".ps1",".bat",".cmd",".json",".toml"}:
                    continue
                if any(x.lower() in {"venv",".venv","runtime","sessions","backups","archive","data","logs",".git"} for x in p.parts):
                    continue
                try:raw=p.read_bytes()
                except Exception:continue
                scanned+=1
                if any(rx.search(raw) for rx in TOKEN_PATTERNS):
                    secret_hits.append(str(p.relative_to(self.root)))
        if secret_hits:
            findings.append({"severity":"high","title":"Possible hard-coded secret exposure indicator",
                "detail":f"{len(secret_hits)} source/config files match secret-like literal patterns.",
                "files":secret_hits[:20]})
        platform=integrated.get("VM_Platform",{}).get("evidence",{})
        doctor=platform.get("doctor_summary") or {}
        if int(doctor.get("FAIL",0) or 0)>0:
            findings.append({"severity":"high","title":"VM Doctor reports failed platform checks",
                             "detail":f"{doctor.get('FAIL')} failed checks."})
        score=100
        if secret_hits:score-=45
        score-=min(30,int(doctor.get("FAIL",0) or 0)*15)
        score-=min(15,int(doctor.get("WARN",0) or 0)*3)
        return {"score":max(0,score),"files_scanned":scanned,"findings":findings,
                "note":"Secret values are never stored in Intelligence results."}
