import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

from marketplace import extract_listing, utc_now

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
  source TEXT NOT NULL DEFAULT 'live',
  PRIMARY KEY(chat_id,message_id)
);
CREATE INDEX IF NOT EXISTS ix_messages_sender ON indexed_messages(sender_id);
CREATE INDEX IF NOT EXISTS ix_messages_date ON indexed_messages(date_utc);
CREATE TABLE IF NOT EXISTS marketplace_listings(
  chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
  sender_id INTEGER, listing_key TEXT NOT NULL, group_key TEXT NOT NULL,
  kind TEXT NOT NULL, status TEXT NOT NULL, price_cents INTEGER,
  currency TEXT, condition TEXT, location TEXT, confidence REAL NOT NULL,
  match_terms TEXT NOT NULL DEFAULT '',
  first_seen_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL,
  PRIMARY KEY(chat_id,message_id)
);
CREATE INDEX IF NOT EXISTS ix_marketplace_group ON marketplace_listings(group_key,last_seen_utc DESC);
CREATE INDEX IF NOT EXISTS ix_marketplace_status ON marketplace_listings(status,kind,last_seen_utc DESC);
CREATE TABLE IF NOT EXISTS marketplace_price_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
  group_key TEXT NOT NULL, price_cents INTEGER NOT NULL, currency TEXT NOT NULL,
  observed_utc TEXT NOT NULL, UNIQUE(chat_id,message_id,price_cents)
);
CREATE INDEX IF NOT EXISTS ix_marketplace_price_group ON marketplace_price_history(group_key,observed_utc DESC);
CREATE TABLE IF NOT EXISTS marketplace_matches(
  demand_chat_id INTEGER NOT NULL, demand_message_id INTEGER NOT NULL,
  supply_chat_id INTEGER NOT NULL, supply_message_id INTEGER NOT NULL,
  score REAL NOT NULL, status TEXT NOT NULL DEFAULT 'new',
  created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
  PRIMARY KEY(demand_chat_id,demand_message_id,supply_chat_id,supply_message_id)
);
CREATE INDEX IF NOT EXISTS ix_marketplace_matches_status ON marketplace_matches(status,updated_utc DESC);
CREATE TABLE IF NOT EXISTS search_audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  query TEXT,
  created_utc TEXT
);
CREATE INDEX IF NOT EXISTS ix_search_audit_user_date ON search_audit(user_id, created_utc DESC);
CREATE TABLE IF NOT EXISTS search_sessions(
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  chat_scope INTEGER,
  raw_query TEXT NOT NULL,
  cross_chat INTEGER NOT NULL DEFAULT 0,
  force_ads INTEGER NOT NULL DEFAULT 0,
  created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_search_sessions_created ON search_sessions(created_utc);
CREATE TABLE IF NOT EXISTS backfill_progress(
  chat_id INTEGER PRIMARY KEY,
  chat_title TEXT,
  chat_username TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  oldest_message_id INTEGER,
  scanned_messages INTEGER NOT NULL DEFAULT 0,
  started_utc TEXT,
  updated_utc TEXT,
  completed_utc TEXT,
  last_error TEXT
);
"""

VALID_SORTS = {"relevant", "newest", "oldest"}


@dataclass
class Query:
    text: str
    user: str | None = None
    days: int | None = None
    limit: int = 10
    ads: bool = False
    available: bool = False
    media: bool = False
    sort: str = "relevant"
    page: int = 1
    terms: tuple[str, ...] = ()
    exact_phrases: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()
    use_or: bool = False

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit

    @property
    def has_text_query(self) -> bool:
        return bool(self.terms or self.exact_phrases)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_term(value: str) -> str:
    parts = re.findall(r"\w+", value, flags=re.UNICODE)
    return " ".join(parts).strip().lower()


def parse_query(raw: str) -> Query:
    user = None
    days = None
    limit = 10
    page = 1
    sort = "relevant"
    ads = bool(re.search(r"(?:^|\s)--ads(?:\s|$)", raw, flags=re.I))
    available = bool(re.search(r"(?:^|\s)--available(?:\s|$)", raw, flags=re.I))
    media = bool(re.search(r"(?:^|\s)--media(?:\s|$)", raw, flags=re.I))

    m = re.search(r"--user\s+(@?[\w.-]+)", raw, flags=re.I)
    if m:
        user = m.group(1).lstrip("@").lower()
    m = re.search(r"--days\s+(\d+)", raw, flags=re.I)
    if m:
        days = max(1, min(int(m.group(1)), 3650))
    m = re.search(r"--limit\s+(\d+)", raw, flags=re.I)
    if m:
        limit = max(1, min(int(m.group(1)), 25))
    m = re.search(r"--page\s+(\d+)", raw, flags=re.I)
    if m:
        page = max(1, min(int(m.group(1)), 10000))
    m = re.search(r"--sort\s+(\w+)", raw, flags=re.I)
    if m and m.group(1).lower() in VALID_SORTS:
        sort = m.group(1).lower()

    working = re.sub(
        r"--(?:user|days|limit|page|sort)\s+\S+|--(?:ads|available|media)",
        " ",
        raw,
        flags=re.I,
    )
    exact_phrases = tuple(
        phrase for phrase in (_clean_term(x) for x in re.findall(r'"([^"\r\n]+)"', working)) if phrase
    )
    working = re.sub(r'"[^"\r\n]+"', " ", working)

    terms: list[str] = []
    excludes: list[str] = []
    use_or = False
    for token in working.split():
        if token.upper() == "OR":
            use_or = True
            continue
        if token.startswith("-") and len(token) > 1:
            cleaned = _clean_term(token[1:])
            if cleaned:
                excludes.extend(cleaned.split())
            continue
        cleaned = _clean_term(token)
        if cleaned:
            terms.extend(cleaned.split())

    text_parts = list(terms) + list(exact_phrases)
    return Query(
        text=" ".join(text_parts),
        user=user,
        days=days,
        limit=limit,
        ads=ads,
        available=available,
        media=media,
        sort=sort,
        page=page,
        terms=tuple(terms),
        exact_phrases=exact_phrases,
        exclude_terms=tuple(excludes),
        use_or=use_or,
    )


def looks_like_ad(text: str) -> bool:
    t = text.lower()
    cues = ["$", "price", "selling", "for sale", "available", "pickup", "delivery", "dm", "pm me"]
    return sum(c in t for c in cues) >= 2


def _fts_quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def build_fts_query(q: Query) -> str | None:
    positives = [_fts_quote(x) for x in q.terms] + [_fts_quote(x) for x in q.exact_phrases]
    if not positives:
        return None
    if q.use_or and len(positives) > 1:
        expression = "(" + " OR ".join(positives) + ")"
    else:
        expression = " ".join(positives)
    for term in q.exclude_terms:
        expression += " NOT " + _fts_quote(term)
    return expression


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self.conn() as c:
            c.executescript(SCHEMA)
            self.fts_enabled = self._migrate(c)

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

    @staticmethod
    def _migrate(c) -> bool:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(indexed_messages)")}
        if "source" not in cols:
            c.execute("ALTER TABLE indexed_messages ADD COLUMN source TEXT NOT NULL DEFAULT 'live'")
        c.execute("CREATE INDEX IF NOT EXISTS ix_messages_source ON indexed_messages(source)")
        market_cols = {r["name"] for r in c.execute("PRAGMA table_info(marketplace_listings)")}
        if "match_terms" not in market_cols:
            c.execute("ALTER TABLE marketplace_listings ADD COLUMN match_terms TEXT NOT NULL DEFAULT ''")
        try:
            c.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5("
                "chat_id UNINDEXED, message_id UNINDEXED, text, "
                "tokenize='unicode61 remove_diacritics 2')"
            )
        except sqlite3.OperationalError as exc:
            if "fts5" in str(exc).lower():
                return False
            raise

        c.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS indexed_messages_fts_ai
            AFTER INSERT ON indexed_messages BEGIN
              INSERT INTO message_fts(chat_id,message_id,text)
              VALUES (new.chat_id,new.message_id,new.text);
            END;
            CREATE TRIGGER IF NOT EXISTS indexed_messages_fts_ad
            AFTER DELETE ON indexed_messages BEGIN
              DELETE FROM message_fts
              WHERE chat_id=old.chat_id AND message_id=old.message_id;
            END;
            CREATE TRIGGER IF NOT EXISTS indexed_messages_fts_au
            AFTER UPDATE OF text ON indexed_messages BEGIN
              DELETE FROM message_fts
              WHERE chat_id=old.chat_id AND message_id=old.message_id;
              INSERT INTO message_fts(chat_id,message_id,text)
              VALUES (new.chat_id,new.message_id,new.text);
            END;
            """
        )
        message_count = c.execute("SELECT COUNT(*) FROM indexed_messages").fetchone()[0]
        fts_count = c.execute("SELECT COUNT(*) FROM message_fts").fetchone()[0]
        if message_count != fts_count:
            c.execute("DELETE FROM message_fts")
            c.execute(
                "INSERT INTO message_fts(chat_id,message_id,text) "
                "SELECT chat_id,message_id,text FROM indexed_messages"
            )
        return True

    def upsert(self, chat_id, title, chat_username, sender_id, sender_username, display_name,
               message_id, date_utc, text, has_media=False, source="live"):
        source = source if source in {"live", "backfill"} else "live"
        with self.conn() as c:
            c.execute(
                "INSERT INTO chats(chat_id,title,username) VALUES(?,?,?) "
                "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, username=excluded.username",
                (chat_id, title, chat_username),
            )
            if sender_id:
                c.execute(
                    "INSERT INTO senders(sender_id,username,display_name) VALUES(?,?,?) "
                    "ON CONFLICT(sender_id) DO UPDATE SET username=excluded.username, display_name=excluded.display_name",
                    (sender_id, sender_username, display_name),
                )
            c.execute(
                """INSERT INTO indexed_messages(
                       chat_id,message_id,sender_id,date_utc,text,has_media,is_ad,is_available,source
                   ) VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(chat_id,message_id) DO UPDATE SET
                       sender_id=COALESCE(excluded.sender_id,indexed_messages.sender_id),
                       date_utc=excluded.date_utc,
                       text=excluded.text,
                       has_media=excluded.has_media,
                       is_ad=excluded.is_ad,
                       source=CASE
                         WHEN indexed_messages.source='live' THEN 'live'
                         ELSE excluded.source
                   END""",
                (chat_id, message_id, sender_id, date_utc, text, int(has_media),
                 int(looks_like_ad(text)), 1, source),
            )
            listing = extract_listing(chat_id, message_id, text)
            prior = c.execute("SELECT first_seen_utc FROM marketplace_listings WHERE chat_id=? AND message_id=?", (chat_id, message_id)).fetchone()
            c.execute("DELETE FROM marketplace_listings WHERE chat_id=? AND message_id=?", (chat_id, message_id))
            if listing:
                now = utc_now()
                first_seen = prior[0] if prior else now
                c.execute("""INSERT INTO marketplace_listings
                    (chat_id,message_id,sender_id,listing_key,group_key,kind,status,price_cents,currency,condition,location,confidence,match_terms,first_seen_utc,last_seen_utc)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (chat_id,message_id,sender_id,listing.listing_key,listing.group_key,listing.kind,listing.status,listing.price_cents,listing.currency,listing.condition,listing.location,listing.confidence,listing.match_terms,first_seen,now))
                if listing.price_cents is not None:
                    c.execute("INSERT OR IGNORE INTO marketplace_price_history(chat_id,message_id,group_key,price_cents,currency,observed_utc) VALUES(?,?,?,?,?,?)", (chat_id,message_id,listing.group_key,listing.price_cents,listing.currency or "AUD",now))
                if source == "live":
                    self._record_market_matches(c, chat_id, message_id, listing.match_terms, listing.kind, listing.status, now)

    @staticmethod
    def _filters(q: Query, chat_id, args: list, *, include_text_fallback=False) -> str:
        sql = ""
        if chat_id is not None:
            sql += " AND m.chat_id=?"
            args.append(chat_id)
        if q.user:
            sql += " AND lower(COALESCE(s.username,''))=?"
            args.append(q.user)
        if q.days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=q.days)).isoformat()
            sql += " AND m.date_utc>=?"
            args.append(cutoff)
        if q.ads:
            sql += " AND m.is_ad=1"
        if q.available:
            sql += " AND m.is_available=1"
        if q.media:
            sql += " AND m.has_media=1"
        if include_text_fallback:
            positive_clauses: list[str] = []
            for term in q.terms:
                positive_clauses.append("lower(m.text) LIKE ?")
                args.append("%" + term.lower() + "%")
            for phrase in q.exact_phrases:
                positive_clauses.append("lower(m.text) LIKE ?")
                args.append("%" + phrase.lower() + "%")
            if positive_clauses:
                joiner = " OR " if q.use_or else " AND "
                sql += " AND (" + joiner.join(positive_clauses) + ")"
            for term in q.exclude_terms:
                sql += " AND lower(m.text) NOT LIKE ?"
                args.append("%" + term.lower() + "%")
        return sql

    def search(self, q: Query, chat_id=None):
        fts_expression = build_fts_query(q) if self.fts_enabled else None
        args: list = []
        if fts_expression:
            sql = """SELECT m.*, c.title chat_title, c.username chat_username,
                            s.username sender_username, s.display_name,
                            bm25(message_fts) AS relevance
                     FROM message_fts
                     JOIN indexed_messages m
                       ON m.chat_id=message_fts.chat_id AND m.message_id=message_fts.message_id
                     LEFT JOIN chats c ON c.chat_id=m.chat_id
                     LEFT JOIN senders s ON s.sender_id=m.sender_id
                     WHERE message_fts MATCH ?"""
            args.append(fts_expression)
            sql += self._filters(q, chat_id, args)
            if q.sort == "oldest":
                sql += " ORDER BY m.date_utc ASC, relevance ASC"
            elif q.sort == "newest":
                sql += " ORDER BY m.date_utc DESC, relevance ASC"
            else:
                sql += " ORDER BY relevance ASC, m.date_utc DESC"
        else:
            sql = """SELECT m.*, c.title chat_title, c.username chat_username,
                            s.username sender_username, s.display_name,
                            NULL AS relevance
                     FROM indexed_messages m
                     LEFT JOIN chats c ON c.chat_id=m.chat_id
                     LEFT JOIN senders s ON s.sender_id=m.sender_id
                     WHERE 1=1"""
            sql += self._filters(q, chat_id, args, include_text_fallback=True)
            if q.sort == "oldest":
                sql += " ORDER BY m.date_utc ASC"
            else:
                sql += " ORDER BY m.date_utc DESC"
        sql += " LIMIT ? OFFSET ?"
        args.extend([q.limit + 1, q.offset])
        with self.conn() as c:
            rows = c.execute(sql, args).fetchall()
        return rows[:q.limit], len(rows) > q.limit

    def count(self, source=None):
        with self.conn() as c:
            if source is None:
                return c.execute("SELECT COUNT(*) FROM indexed_messages").fetchone()[0]
            return c.execute(
                "SELECT COUNT(*) FROM indexed_messages WHERE source=?", (source,)
            ).fetchone()[0]

    def market_search(self, *, kind=None, status=None, min_price=None, max_price=None, limit=20):
        """Owner-facing structured read model; never returns raw message text."""
        clauses, args = ["1=1"], []
        if kind:
            clauses.append("kind=?"); args.append(kind)
        if status:
            clauses.append("status=?"); args.append(status)
        if min_price is not None:
            clauses.append("price_cents>=?"); args.append(int(min_price * 100))
        if max_price is not None:
            clauses.append("price_cents<=?"); args.append(int(max_price * 100))
        limit = max(1, min(int(limit), 50)); args.append(limit)
        with self.conn() as c:
            return c.execute("SELECT * FROM marketplace_listings WHERE " + " AND ".join(clauses) + " ORDER BY last_seen_utc DESC LIMIT ?", args).fetchall()

    def market_listing(self, chat_id, message_id):
        with self.conn() as c:
            return c.execute("SELECT * FROM marketplace_listings WHERE chat_id=? AND message_id=?", (chat_id, message_id)).fetchone()

    def market_price_history(self, group_key, limit=50):
        with self.conn() as c:
            return c.execute("SELECT * FROM marketplace_price_history WHERE group_key=? ORDER BY observed_utc DESC LIMIT ?", (group_key, max(1, min(int(limit), 100)))).fetchall()

    def market_stats(self):
        with self.conn() as c:
            return c.execute("SELECT kind,status,COUNT(*) AS count FROM marketplace_listings GROUP BY kind,status ORDER BY kind,status").fetchall()

    @staticmethod
    def _record_market_matches(c, chat_id, message_id, terms, kind, status, now):
        if not terms or status in {"sold", "pending"}:
            return 0
        wanted = kind == "wanted"
        opposite = "NOT IN ('wanted')" if wanted else "= 'wanted'"
        rows = c.execute("SELECT chat_id,message_id,match_terms FROM marketplace_listings WHERE kind " + opposite + " AND status IN ('active','available') AND match_terms<>''").fetchall()
        inserted = 0
        current = set(terms.split())
        for row in rows:
            overlap = current & set(row["match_terms"].split())
            score = len(overlap) / max(1, len(current | set(row["match_terms"].split())))
            if len(overlap) < 2 or score < 0.35:
                continue
            demand = (chat_id, message_id) if wanted else (row["chat_id"], row["message_id"])
            supply = (row["chat_id"], row["message_id"]) if wanted else (chat_id, message_id)
            cursor = c.execute("INSERT OR IGNORE INTO marketplace_matches(demand_chat_id,demand_message_id,supply_chat_id,supply_message_id,score,status,created_utc,updated_utc) VALUES(?,?,?,?,?,'new',?,?)", (*demand, *supply, round(score, 3), now, now))
            inserted += max(0, cursor.rowcount)
        return inserted

    def market_matches(self, status="new", limit=50):
        with self.conn() as c:
            return c.execute("SELECT * FROM marketplace_matches WHERE status=? ORDER BY updated_utc DESC LIMIT ?", (status, max(1, min(int(limit), 100)))).fetchall()

    def acknowledge_market_match(self, demand_chat_id, demand_message_id, supply_chat_id, supply_message_id):
        with self.conn() as c:
            return c.execute("UPDATE marketplace_matches SET status='acknowledged',updated_utc=? WHERE demand_chat_id=? AND demand_message_id=? AND supply_chat_id=? AND supply_message_id=?", (utc_now(), demand_chat_id, demand_message_id, supply_chat_id, supply_message_id)).rowcount

    def record_search(self, user_id, query):
        with self.conn() as c:
            c.execute(
                "INSERT INTO search_audit(user_id,query,created_utc) VALUES(?,?,?)",
                (user_id, query, utc_now()),
            )

    def recent_searches(self, user_id, limit=10):
        limit = max(1, min(int(limit), 25))
        with self.conn() as c:
            return c.execute(
                "SELECT query,created_utc FROM search_audit WHERE user_id=? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()

    def save_search_session(self, token, user_id, chat_scope, raw_query, cross_chat, force_ads):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with self.conn() as c:
            c.execute("DELETE FROM search_sessions WHERE created_utc<?", (cutoff,))
            c.execute(
                """INSERT OR REPLACE INTO search_sessions(
                       token,user_id,chat_scope,raw_query,cross_chat,force_ads,created_utc
                   ) VALUES(?,?,?,?,?,?,?)""",
                (token, user_id, chat_scope, raw_query, int(cross_chat), int(force_ads), utc_now()),
            )

    def get_search_session(self, token):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM search_sessions WHERE token=? AND created_utc>=?",
                (token, cutoff),
            ).fetchone()

    def get_backfill_progress(self, chat_id):
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM backfill_progress WHERE chat_id=?", (chat_id,)
            ).fetchone()

    def record_backfill_progress(self, chat_id, title, username, *, status,
                                 oldest_message_id=None, scanned_delta=0, error=None):
        now = utc_now()
        existing = self.get_backfill_progress(chat_id)
        started = existing["started_utc"] if existing and existing["started_utc"] else now
        scanned = (existing["scanned_messages"] if existing else 0) + max(0, int(scanned_delta))
        oldest = oldest_message_id
        if oldest is None and existing:
            oldest = existing["oldest_message_id"]
        completed = now if status == "complete" else None
        with self.conn() as c:
            c.execute(
                """INSERT INTO backfill_progress(
                       chat_id,chat_title,chat_username,status,oldest_message_id,
                       scanned_messages,started_utc,updated_utc,completed_utc,last_error
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                       chat_title=excluded.chat_title,
                       chat_username=excluded.chat_username,
                       status=excluded.status,
                       oldest_message_id=excluded.oldest_message_id,
                       scanned_messages=excluded.scanned_messages,
                       started_utc=COALESCE(backfill_progress.started_utc, excluded.started_utc),
                       updated_utc=excluded.updated_utc,
                       completed_utc=excluded.completed_utc,
                       last_error=excluded.last_error""",
                (chat_id, title, username, status, oldest, scanned,
                 started, now, completed, error),
            )

    def backfill_status(self):
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM backfill_progress ORDER BY updated_utc DESC, chat_id"
            ).fetchall()
