
import re, sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS chats(
  chat_id INTEGER PRIMARY KEY, title TEXT, username TEXT
);
CREATE TABLE IF NOT EXISTS senders(
  sender_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT
);
CREATE TABLE IF NOT EXISTS indexed_messages(
  chat_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  sender_id INTEGER,
  date_utc TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '',
  has_media INTEGER NOT NULL DEFAULT 0,
  is_ad INTEGER NOT NULL DEFAULT 0,
  is_available INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(chat_id,message_id)
);
CREATE INDEX IF NOT EXISTS ix_messages_sender ON indexed_messages(sender_id);
CREATE INDEX IF NOT EXISTS ix_messages_date ON indexed_messages(date_utc);
CREATE TABLE IF NOT EXISTS search_audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  query TEXT,
  created_utc TEXT
);
"""

@dataclass
class Query:
    text: str
    user: str | None = None
    days: int | None = None
    limit: int = 10
    ads: bool = False
    available: bool = False

def parse_query(raw: str) -> Query:
    user = None
    days = None
    limit = 10
    ads = "--ads" in raw
    available = "--available" in raw
    m = re.search(r"--user\s+(@?[\w.-]+)", raw)
    if m: user = m.group(1).lstrip("@").lower()
    m = re.search(r"--days\s+(\d+)", raw)
    if m: days = max(1, min(int(m.group(1)), 3650))
    m = re.search(r"--limit\s+(\d+)", raw)
    if m: limit = max(1, min(int(m.group(1)), 50))
    text = re.sub(r"--(?:user|days|limit)\s+\S+|--(?:ads|available)", "", raw).strip()
    return Query(text=text, user=user, days=days, limit=limit, ads=ads, available=available)

def looks_like_ad(text: str) -> bool:
    t = text.lower()
    cues = ["$", "price", "selling", "for sale", "available", "pickup", "delivery", "dm", "pm me"]
    return sum(c in t for c in cues) >= 2

class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self.conn() as c: c.executescript(SCHEMA)
    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    def upsert(self, chat_id, title, chat_username, sender_id, sender_username, display_name,
               message_id, date_utc, text, has_media=False):
        with self.conn() as c:
            c.execute("INSERT INTO chats(chat_id,title,username) VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, username=excluded.username",
                      (chat_id,title,chat_username))
            if sender_id:
                c.execute("INSERT INTO senders(sender_id,username,display_name) VALUES(?,?,?) ON CONFLICT(sender_id) DO UPDATE SET username=excluded.username, display_name=excluded.display_name",
                          (sender_id,sender_username,display_name))
            c.execute("""INSERT INTO indexed_messages(chat_id,message_id,sender_id,date_utc,text,has_media,is_ad,is_available)
                         VALUES(?,?,?,?,?,?,?,1)
                         ON CONFLICT(chat_id,message_id) DO UPDATE SET text=excluded.text, has_media=excluded.has_media, is_ad=excluded.is_ad""",
                      (chat_id,message_id,sender_id,date_utc,text,int(has_media),int(looks_like_ad(text))))
    def search(self, q: Query, chat_id=None):
        sql = """SELECT m.*, c.title chat_title, c.username chat_username, s.username sender_username, s.display_name
                 FROM indexed_messages m
                 LEFT JOIN chats c ON c.chat_id=m.chat_id
                 LEFT JOIN senders s ON s.sender_id=m.sender_id WHERE 1=1"""
        args=[]
        if chat_id is not None: sql += " AND m.chat_id=?"; args.append(chat_id)
        if q.text: sql += " AND lower(m.text) LIKE ?"; args.append("%"+q.text.lower()+"%")
        if q.user: sql += " AND lower(COALESCE(s.username,''))=?"; args.append(q.user)
        if q.days:
            cutoff=(datetime.now(timezone.utc)-timedelta(days=q.days)).isoformat()
            sql += " AND m.date_utc>=?"; args.append(cutoff)
        if q.ads: sql += " AND m.is_ad=1"
        if q.available: sql += " AND m.is_available=1"
        sql += " ORDER BY m.date_utc DESC LIMIT ?"; args.append(q.limit)
        with self.conn() as c: return c.execute(sql,args).fetchall()
    def count(self):
        with self.conn() as c: return c.execute("SELECT COUNT(*) FROM indexed_messages").fetchone()[0]
