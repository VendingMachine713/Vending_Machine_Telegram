from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone


def _schema_version(path):
    try:
        con=sqlite3.connect(path)
        try:
            row=con.execute("SELECT meta_value FROM app_meta WHERE meta_key='schema_version'").fetchone()
            return row[0] if row else "legacy"
        finally:
            con.close()
    except Exception:
        return "legacy"


def _sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def pre_upgrade_backup(settings, target_version: str = "6.0.0"):
    """Create and verify one safety copy before the first major schema migration."""
    if not settings.database_path.exists():
        return None
    current=_schema_version(settings.database_path)
    if current == target_version:
        return None
    try:
        major = int(str(target_version).split('.', 1)[0])
    except Exception:
        major = 0
    prefix = f"pre_v{major}" if major else "pre_upgrade"
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    source_hash=_sha256(settings.database_path)
    existing=sorted(settings.backup_dir.glob(f"{prefix}_*.db"))
    if existing:
        candidate=existing[-1]
        manifest_path=candidate.with_suffix('.json')
        try:
            con=sqlite3.connect(candidate)
            try:
                ok=con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            finally:
                con.close()
            manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
            if ok and manifest.get('source_sha256') == source_hash:
                return candidate
        except Exception:
            pass
        # The old safety copy is corrupt, incomplete, or no longer matches the live pre-upgrade DB.
        # Keep it for audit/history, but create a fresh current snapshot below.
    stamp=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    target=settings.backup_dir / f"{prefix}_{stamp}.db"
    src=sqlite3.connect(settings.database_path)
    dst=sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    con=sqlite3.connect(target)
    try:
        integrity=con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if integrity != 'ok':
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Pre-upgrade safety backup failed SQLite integrity check: {integrity}")
    manifest=target.with_suffix('.json')
    manifest.write_text(json.dumps({
        'file':target.name,'created_at':datetime.now(timezone.utc).isoformat(),
        'source_schema':current,'target_schema':target_version,'source_sha256':source_hash,'sha256':_sha256(target),
        'bytes':target.stat().st_size,'integrity':'ok',
    },indent=2,sort_keys=True),encoding='utf-8')
    return target
