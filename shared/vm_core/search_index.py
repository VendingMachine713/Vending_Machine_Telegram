from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
import sqlite3
from typing import Any, Iterator
from .paths import project_root
from .db import PlatformDB
from .manifests import discover_bots

TEXT_COLS = ("text","message","content","body","caption","description")
CHAT_COLS = ("chat_id","telegram_id","peer_id","dialog_id","group_id","channel_id")
TITLE_COLS = ("title","chat_title","group_title","name")
TIME_COLS = ("date","created_at","created_at_utc","timestamp","sent_at")

class SearchIndex:
    def __init__(self, root: Path | None = None):
        self.root = root or project_root()
        self.path = self.root / "state" / "universal_search.sqlite3"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA busy_timeout=10000")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def init(self) -> None:
        with self.connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS documents(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_key TEXT UNIQUE NOT NULL,
              source_type TEXT NOT NULL,
              source_name TEXT NOT NULL,
              entity_id TEXT,
              title TEXT,
              body TEXT NOT NULL,
              created_at TEXT,
              indexed_at_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(source_type);
            CREATE INDEX IF NOT EXISTS idx_documents_entity ON documents(entity_id);
            """)
            try:
                con.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
                    USING fts5(source_key,source_type,source_name,entity_id,title,body,created_at)""")
            except sqlite3.OperationalError:
                pass

    def rebuild(self, max_external_rows: int = 50000) -> dict[str,int]:
        self.init()
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        pdb = PlatformDB(root=self.root); pdb.init()
        with pdb.connect() as con:
            for r in con.execute("SELECT * FROM destinations"):
                body = " ".join(str(x) for x in [r["title"],r["username"],r["telegram_id"],r["source"]] if x)
                rows.append((f"destination:{r['id']}","destination",r["source"] or "registry",
                             str(r["telegram_id"] or ""),r["title"] or "",body,r["last_seen_utc"],now))
            for r in con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 10000"):
                rows.append((f"event:{r['id']}","event",r["source"],str(r["id"]),
                             r["event_type"],r["payload_json"] or "",r["created_at_utc"],now))
            for r in con.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 10000"):
                body = " ".join(str(x) for x in [r["payload_json"],r["last_error"],r["status"]] if x)
                rows.append((f"job:{r['id']}","job","platform",str(r["id"]),
                             r["job_type"],body,r["created_at_utc"],now))

        external = 0
        for bot in discover_bots(self.root):
            for rel in bot.databases:
                if external >= max_external_rows:
                    break
                low = rel.lower().replace("\\","/")
                if any(x in low for x in ("backup","archive","before_import","universal_search")):
                    continue
                path = Path(bot.path) / rel
                try:
                    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)
                    con.row_factory = sqlite3.Row
                    con.execute("PRAGMA query_only=ON")
                except sqlite3.Error:
                    continue
                try:
                    tables = [x[0] for x in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )]
                    for table in tables:
                        if external >= max_external_rows:
                            break
                        safe = table.replace('"','""')
                        cols = [x[1] for x in con.execute(f'PRAGMA table_info("{safe}")')]
                        text_col = next((c for c in TEXT_COLS if c in cols), None)
                        if not text_col:
                            continue
                        chat_col = next((c for c in CHAT_COLS if c in cols), None)
                        title_col = next((c for c in TITLE_COLS if c in cols), None)
                        time_col = next((c for c in TIME_COLS if c in cols), None)
                        id_col = next((c for c in ("id","message_id","msg_id") if c in cols), None)
                        select = [text_col] + [x for x in (chat_col,title_col,time_col,id_col) if x and x != text_col]
                        sql = 'SELECT ' + ','.join(f'"{c}"' for c in select) + \
                              f' FROM "{safe}" WHERE "{text_col}" IS NOT NULL LIMIT ?'
                        limit = min(10000, max_external_rows-external)
                        for n,row in enumerate(con.execute(sql,(limit,))):
                            body = str(row[text_col] or "").strip()
                            if not body:
                                continue
                            rid = str(row[id_col]) if id_col else str(n)
                            entity = str(row[chat_col]) if chat_col and row[chat_col] is not None else ""
                            title = str(row[title_col]) if title_col and row[title_col] is not None else ""
                            created = str(row[time_col]) if time_col and row[time_col] is not None else None
                            key = f"db:{bot.folder}:{rel}:{table}:{rid}"
                            rows.append((key,"message",f"{bot.folder}:{table}",entity,title,body,created,now))
                            external += 1
                except sqlite3.Error:
                    pass
                finally:
                    con.close()

        with self.connect() as con:
            con.execute("DELETE FROM documents")
            con.executemany("""INSERT OR REPLACE INTO documents
                (source_key,source_type,source_name,entity_id,title,body,created_at,indexed_at_utc)
                VALUES(?,?,?,?,?,?,?,?)""", rows)
            try:
                con.execute("DELETE FROM documents_fts")
                con.execute("""INSERT INTO documents_fts(source_key,source_type,source_name,entity_id,title,body,created_at)
                    SELECT source_key,source_type,source_name,entity_id,title,body,created_at FROM documents""")
            except sqlite3.OperationalError:
                pass
        return {"documents":len(rows),"external_message_rows":external}

    def search(self, query: str, limit: int = 20) -> list[dict[str,Any]]:
        self.init()
        q = (query or "").strip()
        if not q:
            return []
        with self.connect() as con:
            rows = None
            try:
                rows = con.execute("""SELECT source_key,source_type,source_name,entity_id,title,body,created_at
                    FROM documents_fts WHERE documents_fts MATCH ? LIMIT ?""",
                    (q,max(1,limit))).fetchall()
            except sqlite3.OperationalError:
                rows = None
            if rows is None:
                like = f"%{q}%"
                rows = con.execute("""SELECT source_key,source_type,source_name,entity_id,title,body,created_at
                    FROM documents WHERE title LIKE ? OR body LIKE ? ORDER BY id DESC LIMIT ?""",
                    (like,like,max(1,limit))).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str,Any]:
        self.init()
        with self.connect() as con:
            total = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            by_type = {r[0]:r[1] for r in con.execute(
                "SELECT source_type,COUNT(*) FROM documents GROUP BY source_type"
            )}
            last = con.execute("SELECT MAX(indexed_at_utc) FROM documents").fetchone()[0]
        return {"documents":total,"by_type":by_type,"last_indexed_utc":last}
