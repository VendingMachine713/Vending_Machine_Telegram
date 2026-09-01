from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import zipfile
from typing import Any
from .paths import project_root
from .manifests import discover_bots

EXCLUDED_PARTS={".git","__pycache__",".venv","venv","logs","backups","diagnostics","media_cache","downloads","state"}
EXCLUDED_NAMES={".env","secrets.json","credentials.json"}
EXCLUDED_SUFFIXES={".session",".session-journal",".pyc",".db",".sqlite",".sqlite3"}

def _hash(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def _files(bot_dir: Path) -> dict[str,str]:
    out={}
    for p in bot_dir.rglob("*"):
        if not p.is_file(): continue
        rel=p.relative_to(bot_dir)
        if any(part in EXCLUDED_PARTS for part in rel.parts): continue
        if p.name.lower() in EXCLUDED_NAMES or p.suffix.lower() in EXCLUDED_SUFFIXES: continue
        out[rel.as_posix()]=_hash(p)
    return out

def _find_bot(name: str, root: Path):
    matches=[b for b in discover_bots(root) if name.lower() in b.folder.lower()]
    if len(matches)!=1: raise KeyError(f"Could not uniquely resolve bot: {name}")
    return matches[0]

def set_baseline(name: str, root: Path | None = None) -> Path:
    root=root or project_root(); bot=_find_bot(name,root)
    data={"bot":bot.folder,"created_at_utc":datetime.now(timezone.utc).isoformat(),"files":_files(Path(bot.path))}
    path=root/"state"/"release_baselines"/f"{bot.folder}.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    return path

def build_delta(name: str, root: Path | None = None) -> dict[str,Any]:
    root=root or project_root(); bot=_find_bot(name,root); bot_dir=Path(bot.path)
    baseline_path=root/"state"/"release_baselines"/f"{bot.folder}.json"
    if not baseline_path.is_file():
        return {"ok":False,"reason":"No baseline. Run: py vm.py release-baseline <bot>"}
    old=json.loads(baseline_path.read_text(encoding="utf-8"))["files"]
    new=_files(bot_dir)
    changed=[p for p,h in new.items() if old.get(p)!=h]
    deleted=[p for p in old if p not in new]
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out=root/"releases"/f"{bot.folder}_DELTA_{stamp}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest={"schema_version":1,"bot":bot.folder,"created_at_utc":datetime.now(timezone.utc).isoformat(),
              "changed_or_new":changed,"deleted":deleted,"sensitive_files_included":False}
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        for rel in changed: z.write(bot_dir/rel, f"{bot.folder}/{rel}")
        z.writestr("RELEASE_MANIFEST.json",json.dumps(manifest,indent=2))
    return {"ok":True,"path":str(out),"changed_or_new":len(changed),"deleted":len(deleted)}
