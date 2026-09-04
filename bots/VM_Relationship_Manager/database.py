from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS contacts (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    display_name TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    relationship_type TEXT NOT NULL DEFAULT 'unknown',
    activity_status TEXT NOT NULL DEFAULT 'new',
    verification_status TEXT NOT NULL DEFAULT 'unknown',
    manual_importance INTEGER NOT NULL DEFAULT 0,
    relationship_score INTEGER NOT NULL DEFAULT 0,
    trust_score INTEGER NOT NULL DEFAULT 50,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    active_days INTEGER NOT NULL DEFAULT 0,
    typical_cycle_days REAL,
    last_score_update TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    username TEXT,
    display_name TEXT,
    changed_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contact_groups (
    telegram_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    chat_title TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (telegram_id, chat_id),
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_activity (
    telegram_id INTEGER NOT NULL,
    activity_date TEXT NOT NULL,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (telegram_id, activity_date),
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relationship_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tags (
    telegram_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (telegram_id, tag),
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_by INTEGER,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS verification_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_by INTEGER,
    reason TEXT,
    changed_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS risk_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    severity INTEGER NOT NULL DEFAULT 1,
    reason TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    reviewed_by INTEGER,
    reviewed_at TEXT,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attention_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    priority TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE(telegram_id, category, status)
);

CREATE TABLE IF NOT EXISTS admin_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    telegram_id INTEGER,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component TEXT NOT NULL,
    status TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contact_intelligence (
    telegram_id INTEGER PRIMARY KEY,
    health_score INTEGER NOT NULL DEFAULT 50,
    momentum_label TEXT NOT NULL DEFAULT 'learning',
    momentum_score INTEGER NOT NULL DEFAULT 0,
    lifecycle_stage TEXT NOT NULL DEFAULT 'discovered',
    days_overdue INTEGER NOT NULL DEFAULT 0,
    recent_7_interactions INTEGER NOT NULL DEFAULT 0,
    previous_7_interactions INTEGER NOT NULL DEFAULT 0,
    recent_7_active_days INTEGER NOT NULL DEFAULT 0,
    previous_7_active_days INTEGER NOT NULL DEFAULT 0,
    suggested_action TEXT,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relationship_snapshots (
    telegram_id INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    relationship_score INTEGER NOT NULL,
    trust_score INTEGER NOT NULL,
    health_score INTEGER NOT NULL,
    momentum_score INTEGER NOT NULL,
    interaction_count INTEGER NOT NULL,
    active_days INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (telegram_id, snapshot_date),
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_contacts_username ON contacts(username);
CREATE INDEX IF NOT EXISTS idx_contacts_last_seen ON contacts(last_seen);
CREATE INDEX IF NOT EXISTS idx_events_contact ON relationship_events(telegram_id, created_at);
CREATE INDEX IF NOT EXISTS idx_followups_due ON followups(status, due_at);
CREATE INDEX IF NOT EXISTS idx_attention_open ON attention_queue(status, priority);
CREATE INDEX IF NOT EXISTS idx_intelligence_health ON contact_intelligence(health_score);
CREATE INDEX IF NOT EXISTS idx_intelligence_momentum ON contact_intelligence(momentum_label, momentum_score);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.init()

    @contextmanager
    def connect(self):
        with self._lock:
            con = sqlite3.connect(self.path, timeout=30)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            try:
                yield con
                con.commit()
            finally:
                con.close()

    def init(self):
        with self.connect() as con:
            con.executescript(SCHEMA)

    def execute(self, sql: str, params: Iterable[Any] = ()):
        with self.connect() as con:
            cur = con.execute(sql, tuple(params))
            return cur.lastrowid

    def one(self, sql: str, params: Iterable[Any] = ()):
        with self.connect() as con:
            return con.execute(sql, tuple(params)).fetchone()

    def all(self, sql: str, params: Iterable[Any] = ()):
        with self.connect() as con:
            return con.execute(sql, tuple(params)).fetchall()

    def backup_to(self, target: Path) -> Path:
        """Create a transactionally consistent SQLite backup, including WAL state."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        temp.unlink(missing_ok=True)

        with self._lock:
            source = sqlite3.connect(self.path, timeout=30)
            destination = sqlite3.connect(temp, timeout=30)
            try:
                source.execute("PRAGMA busy_timeout=30000")
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
                source.close()

        temp.replace(target)
        return target
