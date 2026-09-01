from __future__ import annotations
from pathlib import Path
from collections import defaultdict
import hashlib

SKIP={"venv",".venv","__pycache__","backups","archive",".git","sessions"}

class TechnicalDebtScanner:
    def __init__(self,root): self.root=Path(root)

    def scan(self):
        bots=self.root/"bots"; hashes=defaultdict(list); huge=[]; markers=[]; files=0
        if not bots.exists(): return {"python_files":0,"duplicate_groups":[],"large_files":[],"markers":[]}
        for p in bots.rglob("*.py"):
            if any(part.lower() in SKIP for part in p.parts): continue
            try:
                raw=p.read_bytes(); text=raw.decode("utf-8",errors="ignore"); files+=1
            except Exception: continue
            if len(text.splitlines())>1200: huge.append({"file":str(p.relative_to(self.root)),"lines":len(text.splitlines())})
            for token in ("TODO","FIXME","HACK"):
                if token in text:
                    markers.append({"file":str(p.relative_to(self.root)),"marker":token,"count":text.count(token)})
            if len(raw)>200:
                hashes[hashlib.sha256(raw).hexdigest()].append(str(p.relative_to(self.root)))
        dup=[v for v in hashes.values() if len(v)>1]
        return {"python_files":files,"duplicate_groups":dup,"large_files":huge,"markers":markers,
                "debt_score": max(0,100-min(60,len(dup)*5)-min(25,len(huge)*5)-min(15,sum(x["count"] for x in markers)))}
