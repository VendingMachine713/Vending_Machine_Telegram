from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .db import Database, utcnow

SEVERITY_ORDER = {"INFO": 10, "WARNING": 20, "IMPORTANT": 30, "CRITICAL": 40}


def severity_at_least(value: str, minimum: str) -> bool:
    return SEVERITY_ORDER.get(value.upper(), 0) >= SEVERITY_ORDER.get(minimum.upper(), 30)


@dataclass(frozen=True)
class Notification:
    id: int
    severity: str
    title: str
    message: str
    attempts: int


class NotificationManager:
    def __init__(self, db: Database):
        self.db = db

    def emit(
        self,
        severity: str,
        title: str,
        message: str,
        *,
        dedupe_key: str | None = None,
        event_type: str | None = None,
        dedupe_window_seconds: int | None = None,
    ):
        """Queue an admin notification.

        ``dedupe_key`` prevents repeated copies.  When ``dedupe_window_seconds``
        is supplied, a previously delivered/failed notification with the same
        key can be recycled after that window.  This lets recurring outages be
        reported again without producing one notification every service loop.
        """
        severity = severity.upper().strip()
        if severity not in SEVERITY_ORDER:
            raise ValueError("invalid notification severity")
        now = utcnow()
        nid = None
        with self.db.connect() as con:
            try:
                cur = con.execute(
                    '''INSERT INTO notifications(created_at,severity,title,message,status,attempts,dedupe_key)
                       VALUES(?,?,?,?, 'pending',0,?)''',
                    (now, severity, title[:160], message[:4000], dedupe_key),
                )
                nid = int(cur.lastrowid)
            except Exception as exc:
                if "UNIQUE" not in str(exc).upper() or not dedupe_key:
                    raise
                row = con.execute(
                    "SELECT id,created_at,status FROM notifications WHERE dedupe_key=?",
                    (dedupe_key,),
                ).fetchone()
                if not row:
                    return None
                if not dedupe_window_seconds:
                    return int(row["id"])
                try:
                    created = datetime.fromisoformat(row["created_at"])
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - created).total_seconds()
                except Exception:
                    age = 0
                if age < max(1, int(dedupe_window_seconds)):
                    return int(row["id"])
                con.execute(
                    '''UPDATE notifications
                       SET created_at=?,severity=?,title=?,message=?,status='pending',attempts=0,
                           sent_at=NULL,last_error=NULL
                       WHERE id=?''',
                    (now, severity, title[:160], message[:4000], int(row["id"])),
                )
                nid = int(row["id"])
        self.db.event(
            severity if severity != "IMPORTANT" else "WARNING",
            event_type or "notification",
            f"{title}: {message}"[:800],
        )
        return nid

    def pending(self, minimum: str = "IMPORTANT", limit: int = 20) -> list[Notification]:
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT * FROM notifications WHERE status='pending' ORDER BY id LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [
            Notification(int(r["id"]), r["severity"], r["title"], r["message"], int(r["attempts"]))
            for r in rows
            if severity_at_least(r["severity"], minimum)
        ]

    def mark_sent(self, notification_id: int):
        with self.db.connect() as con:
            con.execute(
                "UPDATE notifications SET status='sent',sent_at=?,last_error=NULL WHERE id=?",
                (utcnow(), notification_id),
            )

    def mark_error(self, notification_id: int, error: str, max_attempts: int = 5):
        with self.db.connect() as con:
            row = con.execute("SELECT attempts FROM notifications WHERE id=?", (notification_id,)).fetchone()
            if not row:
                return
            attempts = int(row[0]) + 1
            status = "failed" if attempts >= max_attempts else "pending"
            con.execute(
                "UPDATE notifications SET attempts=?,status=?,last_error=? WHERE id=?",
                (attempts, status, error[:800], notification_id),
            )

    def prune(self, days: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat(timespec="seconds")
        with self.db.connect() as con:
            cur = con.execute(
                "DELETE FROM notifications WHERE status IN ('sent','failed') AND created_at<?",
                (cutoff,),
            )
            return cur.rowcount
