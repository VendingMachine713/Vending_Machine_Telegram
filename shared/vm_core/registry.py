from __future__ import annotations
from pathlib import Path
import sqlite3
from typing import Any
from .paths import project_root
from .manifests import discover_bots
from .db import PlatformDB, utcnow

ID_COLUMNS = ("telegram_id","chat_id","entity_id","peer_id","dialog_id","group_id","channel_id")
TITLE_COLUMNS = ("title","name","chat_title","group_title")
USERNAME_COLUMNS = ("username","handle")
ACTIVE_COLUMNS = ("active","enabled","is_enabled")

def sync_accounts(root: Path | None = None) -> int:
    root = root or project_root()
    db = PlatformDB(root=root); db.init()
    count = 0
    with db.connect() as con:
        for b in discover_bots(root):
            for rel in b.session_files:
                p = Path(b.path) / rel
                label = p.stem
                con.execute("""
                    INSERT INTO accounts(label,session_path,source,last_seen_utc)
                    VALUES(?,?,?,?)
                    ON CONFLICT(session_path) DO UPDATE SET
                      label=excluded.label, source=excluded.source, last_seen_utc=excluded.last_seen_utc
                """, (label, str(p), b.folder, utcnow()))
                count += 1
    return count

def _candidate_table_columns(con: sqlite3.Connection):
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        safe = table.replace('"','""')
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{safe}")')]
        yield table, cols

def sync_destinations(root: Path | None = None) -> dict[str,int]:
    root = root or project_root()
    pdb = PlatformDB(root=root); pdb.init()
    scanned, imported = 0, 0
    for bot in discover_bots(root):
        for rel in bot.databases:
            path = Path(bot.path) / rel
            # Avoid importing from backups where path/name indicates backup.
            if any(x in rel.lower() for x in ("backup","before_import","archive")):
                continue
            try:
                con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)
                con.row_factory = sqlite3.Row
            except sqlite3.Error:
                continue
            try:
                for table, cols in _candidate_table_columns(con):
                    scanned += 1
                    id_col = next((c for c in ID_COLUMNS if c in cols), None)
                    if not id_col:
                        continue
                    title_col = next((c for c in TITLE_COLUMNS if c in cols), None)
                    username_col = next((c for c in USERNAME_COLUMNS if c in cols), None)
                    active_col = next((c for c in ACTIVE_COLUMNS if c in cols), None)
                    select_cols = [id_col] + [c for c in (title_col,username_col,active_col) if c]
                    safe_table = table.replace('"','""')
                    sql = 'SELECT ' + ','.join(f'"{c}"' for c in select_cols) + f' FROM "{safe_table}" LIMIT 10000'
                    for row in con.execute(sql):
                        tid = row[id_col]
                        if tid is None:
                            continue
                        title = row[title_col] if title_col else None
                        username = row[username_col] if username_col else None
                        active = row[active_col] if active_col else 1
                        try: active_int = 1 if bool(active) else 0
                        except Exception: active_int = 1
                        with pdb.connect() as pc:
                            pc.execute("""
                                INSERT INTO destinations(telegram_id,title,username,active,source,last_seen_utc)
                                VALUES(?,?,?,?,?,?)
                                ON CONFLICT(telegram_id) DO UPDATE SET
                                   title=COALESCE(excluded.title,destinations.title),
                                   username=COALESCE(excluded.username,destinations.username),
                                   active=excluded.active,
                                   source=excluded.source,
                                   last_seen_utc=excluded.last_seen_utc
                            """,(str(tid),title,username,active_int,f"{bot.folder}:{rel}:{table}",utcnow()))
                        imported += 1
            except sqlite3.Error:
                pass
            finally:
                con.close()
    return {"tables_scanned":scanned,"rows_imported_or_refreshed":imported}

def registry_summary(root: Path | None = None) -> dict[str,int]:
    root = root or project_root()
    db=PlatformDB(root=root); db.init()
    with db.connect() as con:
        destinations = con.execute("SELECT COUNT(*) FROM destinations").fetchone()[0]
        accounts = con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    return {"destinations":destinations,"accounts":accounts}
