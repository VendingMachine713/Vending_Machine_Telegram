from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from typing import Any
from .paths import project_root
from .manifests import discover_bots
from .db import PlatformDB, utcnow
from .logging_setup import log_event

EXCLUDED_DIR_NAMES={".git","__pycache__",".venv","venv","logs","diagnostics","backups","media_cache","downloads"}
EXCLUDED_FILE_NAMES={".env","secrets.json","credentials.json"}
EXCLUDED_SUFFIXES={".session",".session-journal",".pyc"}

def _include(path: Path, root: Path) -> bool:
    rel=path.relative_to(root)
    if any(part in EXCLUDED_DIR_NAMES for part in rel.parts): return False
    if path.name.lower() in EXCLUDED_FILE_NAMES: return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES: return False
    return path.is_file()

def create_backup(root: Path | None = None, kind: str = "manual") -> Path:
    root=root or project_root()
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out=root/"backups"/f"vm_backup_{kind}_{stamp}.zip"
    out.parent.mkdir(parents=True,exist_ok=True)
    manifest={"schema_version":1,"kind":kind,"created_at_utc":utcnow(),"files":[],"sqlite_backups":[]}
    with tempfile.TemporaryDirectory() as tmp:
        temp=Path(tmp)
        # Safely snapshot SQLite databases with SQLite backup API.
        db_files=[]
        for pat in ("*.db","*.sqlite","*.sqlite3"):
            db_files.extend(root.rglob(pat))
        sqlite_set={p.resolve() for p in db_files if "backups" not in p.parts}
        for p in sorted(sqlite_set):
            try:
                rel=p.relative_to(root)
            except ValueError:
                continue
            target=temp/"sqlite"/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            try:
                src=sqlite3.connect(f"file:{p.as_posix()}?mode=ro",uri=True,timeout=3)
                dst=sqlite3.connect(target)
                try: src.backup(dst)
                finally:
                    src.close(); dst.close()
                manifest["sqlite_backups"].append(rel.as_posix())
            except sqlite3.Error:
                pass

        with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
            for p in sorted(root.rglob("*")):
                if not _include(p,root): continue
                if p.resolve() in sqlite_set: continue
                rel=p.relative_to(root)
                # Limit to platform/shared/source/config/docs/tests plus bot source.
                if rel.parts[0] not in {"shared","tools","tests","config","docs","bots","vm.py","VM_PROJECT.json","pyproject.toml"} and p.name not in {"vm.py","VM_PROJECT.json","pyproject.toml"}:
                    continue
                z.write(p,rel.as_posix())
                manifest["files"].append(rel.as_posix())
            for p in (temp/"sqlite").rglob("*") if (temp/"sqlite").exists() else []:
                if p.is_file():
                    rel=p.relative_to(temp/"sqlite")
                    z.write(p,("database_snapshots/"+rel.as_posix()))
            z.writestr("BACKUP_MANIFEST.json",json.dumps(manifest,indent=2,ensure_ascii=False))

    db=PlatformDB(root=root); db.init()
    with db.connect() as con:
        con.execute("INSERT OR IGNORE INTO backups(path,kind,created_at_utc,manifest_json) VALUES(?,?,?,?)",
                    (str(out),kind,manifest["created_at_utc"],json.dumps(manifest)))
    log_event("backup_created",data={"path":str(out),"kind":kind},root=root)
    prune_backups(root, keep=10)
    return out

def list_backups(root: Path | None = None) -> list[Path]:
    root=root or project_root()
    return sorted((root/"backups").glob("vm_backup_*.zip"),key=lambda p:p.stat().st_mtime,reverse=True)

def rollback_preview(backup: Path, root: Path | None = None) -> dict[str,Any]:
    root=root or project_root()
    with zipfile.ZipFile(backup) as z:
        names=z.namelist()
    source=[n for n in names if not n.startswith("database_snapshots/") and n!="BACKUP_MANIFEST.json"]
    dbs=[n for n in names if n.startswith("database_snapshots/")]
    return {"backup":str(backup),"source_files_to_restore":len(source),"database_snapshots_to_restore":len(dbs),"dry_run":True}

def rollback(backup: Path, root: Path | None = None, apply: bool = False) -> dict[str,Any]:
    root=root or project_root()
    preview=rollback_preview(backup,root)
    if not apply: return preview
    safety=create_backup(root,kind="pre_rollback")
    with tempfile.TemporaryDirectory() as tmp:
        t=Path(tmp)
        with zipfile.ZipFile(backup) as z: z.extractall(t)
        for p in t.rglob("*"):
            if not p.is_file() or p.name=="BACKUP_MANIFEST.json": continue
            rel=p.relative_to(t)
            if rel.parts and rel.parts[0]=="database_snapshots":
                db_rel=Path(*rel.parts[1:])
                dest=root/db_rel
            else:
                dest=root/rel
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,dest)
    log_event("rollback_applied",level="WARN",data={"backup":str(backup),"safety_backup":str(safety)},root=root)
    preview.update({"dry_run":False,"safety_backup":str(safety)})
    return preview


def prune_backups(root: Path | None = None, keep: int = 10) -> list[str]:
    root = root or project_root()
    backups = list_backups(root)
    removed = []
    for p in backups[max(1, keep):]:
        try:
            p.unlink()
            removed.append(str(p))
        except OSError:
            pass
    return removed
