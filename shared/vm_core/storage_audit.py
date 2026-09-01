from __future__ import annotations
from pathlib import Path
import os
import shutil
from typing import Any
from .paths import project_root

SKIP={".git",".venv","venv","__pycache__"}

def _tree_size(path:Path)->int:
    total=0
    try:
        for root,dirs,files in os.walk(path):
            dirs[:]=[d for d in dirs if d not in SKIP]
            for name in files:
                try:
                    total+=(Path(root)/name).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total

def audit(root:Path|None=None,topn:int=20)->dict[str,Any]:
    root=root or project_root()
    usage=shutil.disk_usage(root)
    top_dirs=[]
    for p in root.iterdir():
        if p.is_dir() and p.name not in SKIP:
            top_dirs.append({"path":p.name,"bytes":_tree_size(p)})
    top_dirs.sort(key=lambda x:x["bytes"],reverse=True)
    largest=[]
    for p in root.rglob("*"):
        if not p.is_file() or any(part in SKIP for part in p.relative_to(root).parts):
            continue
        try:
            size=p.stat().st_size
        except OSError:
            continue
        largest.append({"path":p.relative_to(root).as_posix(),"bytes":size})
    largest.sort(key=lambda x:x["bytes"],reverse=True)
    return {
        "disk_free_gib":round(usage.free/(1024**3),2),
        "disk_total_gib":round(usage.total/(1024**3),2),
        "project_bytes":sum(x["bytes"] for x in top_dirs),
        "top_directories":top_dirs[:topn],
        "largest_files":largest[:topn],
        "deletion_performed":False,
    }
