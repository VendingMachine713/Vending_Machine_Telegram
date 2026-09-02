import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import parse_query, utc_now

WATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_searches(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  raw_query TEXT NOT NULL,
  chat_scope INTEGER,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL,
  last_match_utc TEXT,
  failure_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  UNIQUE(owner_user_id, name)
);
CREATE INDEX IF NOT EXISTS ix_saved_searches_owner ON saved_searches(owner_user_id, enabled);
CREATE INDEX IF NOT EXISTS ix_saved_searches_scope ON saved_searches(chat_scope, enabled);

CREATE TABLE IF NOT EXISTS alert_queue(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  watch_id INTEGER NOT NULL,
  owner_user_id INTEGER NOT NULL,
  chat_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  due_utc TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  sent_utc TEXT,
  last_error TEXT,
  UNIQUE(watch_id, chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS ix_alert_queue_due ON alert_queue(status, due_utc);
CREATE INDEX IF NOT EXISTS ix_alert_queue_owner ON alert_queue(owner_user_id, status);
"""


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def message_matches(raw_query, row) -> bool:
    q = parse_query(raw_query)
    text = (row["text"] or "").lower()
    username = (row["sender_username"] or "").lower()

    if q.user and username != q.user:
        return False
    if q.days:
        message_dt = _parse_dt(row["date_utc"])
        if not message_dt:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(days=q.days)
        if message_dt < cutoff:
            return False
    if q.ads and not bool(row["is_ad"]):
        return False
    if q.available and not bool(row["is_available"]):
        return False
    if q.media and not bool(row["has_media"]):
        return False

    positives = list(q.terms) + list(q.exact_phrases)
    if positives:
        matches = [term.lower() in text for term in positives]
        if q.use_or:
            if not any(matches):
                return False
        elif not all(matches):
            return False
    for term in q.exclude_terms:
        if term.lower() in text:
            return False
    return bool(positives or q.ads or q.available or q.media or q.user)


class WatchStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        with self.conn() as c:
            c.executescript(WATCH_SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def count_for_owner(self, owner_user_id):
        with self.conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM saved_searches WHERE owner_user_id=?",
                (owner_user_id,),
            ).fetchone()[0]

    def save(self, owner_user_id, name, raw_query, chat_scope):
        now = utc_now()
        with self.conn() as c:
            c.execute(
                """INSERT INTO saved_searches(
                       owner_user_id,name,raw_query,chat_scope,enabled,created_utc,updated_utc
                   ) VALUES(?,?,?,?,1,?,?)
                   ON CONFLICT(owner_user_id,name) DO UPDATE SET
                       raw_query=excluded.raw_query,
                       chat_scope=excluded.chat_scope,
                       enabled=1,
                       updated_utc=excluded.updated_utc,
                       failure_count=0,
                       last_error=NULL""",
                (owner_user_id, name, raw_query, chat_scope, now, now),
            )
            return c.execute(
                "SELECT * FROM saved_searches WHERE owner_user_id=? AND name=?",
                (owner_user_id, name),
            ).fetchone()

    def list_for_owner(self, owner_user_id):
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM saved_searches WHERE owner_user_id=? ORDER BY id",
                (owner_user_id,),
            ).fetchall()

    def set_enabled(self, owner_user_id, watch_id, enabled):
        with self.conn() as c:
            cur = c.execute(
                "UPDATE saved_searches SET enabled=?,updated_utc=? "
                "WHERE id=? AND owner_user_id=?",
                (int(bool(enabled)), utc_now(), watch_id, owner_user_id),
            )
            return cur.rowcount > 0

    def delete(self, owner_user_id, watch_id):
        with self.conn() as c:
            row = c.execute(
                "SELECT id FROM saved_searches WHERE id=? AND owner_user_id=?",
                (watch_id, owner_user_id),
            ).fetchone()
            if not row:
                return False
            c.execute("DELETE FROM alert_queue WHERE watch_id=?", (watch_id,))
            c.execute("DELETE FROM saved_searches WHERE id=?", (watch_id,))
            return True

    def get_message(self, chat_id, message_id):
        with self.conn() as c:
            return c.execute(
                """SELECT m.*, c.title chat_title, c.username chat_username,
                          s.username sender_username, s.display_name
                   FROM indexed_messages m
                   LEFT JOIN chats c ON c.chat_id=m.chat_id
                   LEFT JOIN senders s ON s.sender_id=m.sender_id
                   WHERE m.chat_id=? AND m.message_id=?""",
                (chat_id, message_id),
            ).fetchone()

    def candidate_watches(self, chat_id):
        with self.conn() as c:
            return c.execute(
                """SELECT * FROM saved_searches
                   WHERE enabled=1 AND (chat_scope IS NULL OR chat_scope=?)
                   ORDER BY id""",
                (chat_id,),
            ).fetchall()

    def enqueue_matches(self, row):
        if not row:
            return 0
        now = utc_now()
        created = 0
        with self.conn() as c:
            watches = c.execute(
                """SELECT * FROM saved_searches
                   WHERE enabled=1 AND (chat_scope IS NULL OR chat_scope=?)
                   ORDER BY id""",
                (row["chat_id"],),
            ).fetchall()
            for watch in watches:
                if not message_matches(watch["raw_query"], row):
                    continue
                cur = c.execute(
                    """INSERT OR IGNORE INTO alert_queue(
                           watch_id,owner_user_id,chat_id,message_id,status,attempts,due_utc,created_utc
                       ) VALUES(?,?,?,?, 'pending',0,?,?)""",
                    (watch["id"], watch["owner_user_id"], row["chat_id"], row["message_id"], now, now),
                )
                created += cur.rowcount
        return created

    def due_alerts(self, limit=20):
        limit = max(1, min(int(limit), 100))
        with self.conn() as c:
            return c.execute(
                """SELECT q.id alert_id,q.attempts,q.owner_user_id,q.watch_id,
                          w.name watch_name,w.raw_query,w.chat_scope,
                          m.*, c.title chat_title,c.username chat_username,
                          s.username sender_username,s.display_name
                   FROM alert_queue q
                   JOIN saved_searches w ON w.id=q.watch_id AND w.enabled=1
                   JOIN indexed_messages m ON m.chat_id=q.chat_id AND m.message_id=q.message_id
                   LEFT JOIN chats c ON c.chat_id=m.chat_id
                   LEFT JOIN senders s ON s.sender_id=m.sender_id
                   WHERE q.status IN ('pending','retry') AND q.due_utc<=?
                   ORDER BY q.due_utc,q.id LIMIT ?""",
                (utc_now(), limit),
            ).fetchall()

    def mark_sent(self, alert_id, watch_id):
        now = utc_now()
        with self.conn() as c:
            c.execute(
                "UPDATE alert_queue SET status='sent',sent_utc=?,last_error=NULL WHERE id=?",
                (now, alert_id),
            )
            c.execute(
                """UPDATE saved_searches SET last_match_utc=?,failure_count=0,last_error=NULL,
                          updated_utc=? WHERE id=?""",
                (now, now, watch_id),
            )

    def mark_retry(self, alert_id, error, attempts):
        attempts = int(attempts) + 1
        delay = min(3600, 30 * (2 ** min(attempts - 1, 7)))
        due = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        status = "failed" if attempts >= 5 else "retry"
        with self.conn() as c:
            c.execute(
                """UPDATE alert_queue SET status=?,attempts=?,due_utc=?,last_error=?
                   WHERE id=?""",
                (status, attempts, due, str(error)[:500], alert_id),
            )
            if status == "failed":
                row = c.execute(
                    "SELECT watch_id FROM alert_queue WHERE id=?", (alert_id,)
                ).fetchone()
                if row:
                    c.execute(
                        """UPDATE saved_searches SET failure_count=failure_count+1,
                                  last_error=?,updated_utc=? WHERE id=?""",
                        (str(error)[:500], utc_now(), row["watch_id"]),
                    )
                    c.execute(
                        """UPDATE saved_searches SET enabled=0
                           WHERE id=? AND failure_count>=3""",
                        (row["watch_id"],),
                    )
        return status, due

    def queue_status_for_owner(self, owner_user_id):
        with self.conn() as c:
            return c.execute(
                """SELECT status,COUNT(*) count FROM alert_queue
                   WHERE owner_user_id=? GROUP BY status ORDER BY status""",
                (owner_user_id,),
            ).fetchall()

    def cleanup_alert_history(self, sent_days=30, failed_days=90):
        sent_cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(sent_days)))).isoformat()
        failed_cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(failed_days)))).isoformat()
        with self.conn() as c:
            sent = c.execute(
                "DELETE FROM alert_queue WHERE status='sent' AND sent_utc IS NOT NULL AND sent_utc<?",
                (sent_cutoff,),
            ).rowcount
            failed = c.execute(
                "DELETE FROM alert_queue WHERE status='failed' AND created_utc<?",
                (failed_cutoff,),
            ).rowcount
        return max(0, sent) + max(0, failed)
