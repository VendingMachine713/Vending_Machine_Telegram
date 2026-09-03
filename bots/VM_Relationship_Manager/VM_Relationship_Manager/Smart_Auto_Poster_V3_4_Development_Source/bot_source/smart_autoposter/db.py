from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .redaction import redact_text

SCHEMA_VERSION = 6

SCHEMA = r'''
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    account_key TEXT PRIMARY KEY,
    session_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    authorized INTEGER,
    identity TEXT,
    telegram_user_id INTEGER,
    cooldown_until TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_heartbeat_at TEXT,
    health_score INTEGER NOT NULL DEFAULT 100,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS destinations (
    group_id INTEGER PRIMARY KEY,
    group_name TEXT NOT NULL,
    chat_type TEXT,
    username TEXT,
    forum INTEGER NOT NULL DEFAULT 0,
    topic_id INTEGER,
    primary_access INTEGER NOT NULL DEFAULT 0,
    secondary_access INTEGER NOT NULL DEFAULT 0,
    preferred_account TEXT NOT NULL DEFAULT 'primary',
    mode TEXT NOT NULL DEFAULT 'review',
    enabled INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 1,
    protected INTEGER NOT NULL DEFAULT 0,
    never_auto_post INTEGER NOT NULL DEFAULT 0,
    min_interval_seconds INTEGER NOT NULL DEFAULT 0,
    quiet_start TEXT,
    quiet_end TEXT,
    last_post_at TEXT,
    next_eligible_at TEXT,
    last_seen_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    quarantine_until TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS destination_tags (
    group_id INTEGER NOT NULL REFERENCES destinations(group_id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (group_id, tag)
);

CREATE TABLE IF NOT EXISTS content (
    content_id TEXT PRIMARY KEY,
    caption TEXT NOT NULL DEFAULT '',
    media_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    source_dir TEXT,
    fingerprint TEXT,
    lifecycle_state TEXT NOT NULL DEFAULT 'ready',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_tags (
    content_id TEXT NOT NULL REFERENCES content(content_id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY(content_id, tag)
);

CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    content_id TEXT NOT NULL REFERENCES content(content_id),
    enabled INTEGER NOT NULL DEFAULT 0,
    lifecycle_state TEXT NOT NULL DEFAULT 'draft',
    last_preview_at TEXT,
    priority INTEGER NOT NULL DEFAULT 50,
    target_tags TEXT NOT NULL DEFAULT '',
    exclude_tags TEXT NOT NULL DEFAULT '',
    rotation_mode TEXT NOT NULL DEFAULT 'sequential',
    min_content_reuse_seconds INTEGER NOT NULL DEFAULT 0,
    allow_protected INTEGER NOT NULL DEFAULT 0,
    conflict_gap_seconds INTEGER NOT NULL DEFAULT 0,
    spread_seconds INTEGER NOT NULL DEFAULT 0,
    start_at TEXT,
    end_at TEXT,
    min_destination_interval_seconds INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT '',
    target_collections TEXT NOT NULL DEFAULT '',
    max_cycles INTEGER NOT NULL DEFAULT 0,
    completed_cycles INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign_content (
    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    content_id TEXT NOT NULL REFERENCES content(content_id),
    position INTEGER NOT NULL DEFAULT 0,
    weight INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL,
    PRIMARY KEY (campaign_id, content_id)
);
CREATE INDEX IF NOT EXISTS idx_campaign_content_active ON campaign_content(campaign_id, enabled, position);

CREATE TABLE IF NOT EXISTS campaign_relations (
    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    related_campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'min_gap',
    min_gap_seconds INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id, related_campaign_id, relation_type),
    CHECK(campaign_id <> related_campaign_id)
);

CREATE TABLE IF NOT EXISTS campaign_destination_state (
    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES destinations(group_id) ON DELETE CASCADE,
    last_content_id TEXT REFERENCES content(content_id),
    last_used_at TEXT,
    send_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, group_id)
);

CREATE TABLE IF NOT EXISTS content_usage (
    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES destinations(group_id) ON DELETE CASCADE,
    content_id TEXT NOT NULL REFERENCES content(content_id),
    last_used_at TEXT,
    use_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, group_id, content_id)
);

CREATE TABLE IF NOT EXISTS campaign_schedules (
    campaign_id TEXT PRIMARY KEY REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    mode TEXT NOT NULL DEFAULT 'manual',
    interval_seconds INTEGER,
    daily_times_json TEXT NOT NULL DEFAULT '[]',
    days_json TEXT NOT NULL DEFAULT '[]',
    timezone TEXT NOT NULL DEFAULT 'Australia/Adelaide',
    next_run_at TEXT,
    last_run_at TEXT,
    jitter_seconds INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedule_due ON campaign_schedules(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    run_key TEXT,
    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
    group_id INTEGER NOT NULL REFERENCES destinations(group_id),
    content_id TEXT REFERENCES content(content_id),
    account_key TEXT,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 4,
    error_kind TEXT,
    last_error TEXT,
    telegram_message_ids TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queue_due ON queue(status, due_at);
CREATE INDEX IF NOT EXISTS idx_queue_campaign ON queue(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_queue_group_due ON queue(group_id, status, due_at);
CREATE INDEX IF NOT EXISTS idx_queue_account_status ON queue(account_key, status);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    event_type TEXT NOT NULL,
    account_key TEXT,
    group_id INTEGER,
    campaign_id TEXT,
    message TEXT NOT NULL,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_created_type ON events(created_at, event_type);
CREATE INDEX IF NOT EXISTS idx_events_severity_created ON events(severity, created_at);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    sent_at TEXT,
    last_error TEXT,
    dedupe_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_pending ON notifications(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_dedupe ON notifications(dedupe_key) WHERE dedupe_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS heartbeats (
    component TEXT PRIMARY KEY,
    last_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    details TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);



CREATE TABLE IF NOT EXISTS destination_collections (
    collection_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    include_tags TEXT NOT NULL DEFAULT '',
    exclude_tags TEXT NOT NULL DEFAULT '',
    required_access TEXT NOT NULL DEFAULT 'any',
    mode TEXT NOT NULL DEFAULT 'any',
    forum_only INTEGER NOT NULL DEFAULT 0,
    include_protected INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automation_rules (
    rule_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled INTEGER NOT NULL DEFAULT 1,
    condition_json TEXT NOT NULL DEFAULT '{}',
    action_json TEXT NOT NULL DEFAULT '{}',
    last_applied_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rules_enabled_priority ON automation_rules(enabled, priority, rule_id);

CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'INFO',
    target_type TEXT,
    target_id TEXT,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    suggested_action_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open',
    dismissed_at TEXT,
    applied_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_recommendations_status_created ON recommendations(status, created_at);

CREATE TABLE IF NOT EXISTS update_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    version TEXT NOT NULL,
    previous_version TEXT,
    status TEXT NOT NULL,
    package_name TEXT,
    details TEXT
);
'''


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA busy_timeout=30000")
            yield con
            con.commit()
        finally:
            con.close()

    @staticmethod
    def _columns(con, table: str) -> set[str]:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}

    def _migrate(self, con):
        # Additive migrations keep existing V2 databases usable in-place.
        additions = {
            "accounts": {
                "telegram_user_id": "INTEGER",
                "last_success_at": "TEXT",
                "last_failure_at": "TEXT",
                "last_heartbeat_at": "TEXT",
                "health_score": "INTEGER NOT NULL DEFAULT 100",
            },
            "destinations": {
                "protected": "INTEGER NOT NULL DEFAULT 0",
                "never_auto_post": "INTEGER NOT NULL DEFAULT 0",
                "last_seen_at": "TEXT",
            },
            "content": {
                "source_dir": "TEXT",
                "fingerprint": "TEXT",
                "lifecycle_state": "TEXT NOT NULL DEFAULT 'ready'",
            },
            "campaigns": {
                "exclude_tags": "TEXT NOT NULL DEFAULT ''",
                "rotation_mode": "TEXT NOT NULL DEFAULT 'sequential'",
                "min_content_reuse_seconds": "INTEGER NOT NULL DEFAULT 0",
                "allow_protected": "INTEGER NOT NULL DEFAULT 0",
                "conflict_gap_seconds": "INTEGER NOT NULL DEFAULT 0",
                "spread_seconds": "INTEGER NOT NULL DEFAULT 0",
                "lifecycle_state": "TEXT NOT NULL DEFAULT 'draft'",
                "last_preview_at": "TEXT",
                "category": "TEXT NOT NULL DEFAULT ''",
                "target_collections": "TEXT NOT NULL DEFAULT ''",
                "max_cycles": "INTEGER NOT NULL DEFAULT 0",
                "completed_cycles": "INTEGER NOT NULL DEFAULT 0",
            },
            "queue": {
                "run_key": "TEXT",
                "content_id": "TEXT",
                "error_kind": "TEXT",
                "resolved_at": "TEXT",
            },
        }
        for table, columns in additions.items():
            existing = self._columns(con, table)
            for name, sql_type in columns.items():
                if name not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")

        # V2.3 normalized old one-content campaigns into campaign_content.
        con.execute('''INSERT OR IGNORE INTO campaign_content(campaign_id,content_id,position,weight,enabled,added_at)
                       SELECT c.campaign_id,c.content_id,0,1,1,COALESCE(c.created_at,?)
                       FROM campaigns c
                       JOIN content ct ON ct.content_id=c.content_id''', (utcnow(),))
        con.execute('''UPDATE queue SET content_id=(SELECT c.content_id FROM campaigns c WHERE c.campaign_id=queue.campaign_id)
                       WHERE content_id IS NULL''')

        # Normalize lifecycle state for databases upgraded from pre-V2.4.
        con.execute("UPDATE campaigns SET lifecycle_state=CASE WHEN enabled=1 THEN 'active' ELSE 'draft' END WHERE lifecycle_state IS NULL OR lifecycle_state='' OR lifecycle_state='draft' AND enabled=1")
        con.execute("UPDATE content SET lifecycle_state=CASE WHEN enabled=1 THEN 'ready' ELSE 'disabled' END WHERE lifecycle_state IS NULL OR lifecycle_state=''")
        # Index depends on the V2.4 fingerprint column, so create it only after additive ALTERs.
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_content_fingerprint ON content(fingerprint) WHERE fingerprint IS NOT NULL AND fingerprint<>''")

    def init(self):
        with self.connect() as con:
            con.executescript(SCHEMA)
            self._migrate(con)
            con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))

    def backup_to(self, destination: Path):
        """Create a consistent online SQLite backup, including WAL-resident data."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(self.path, timeout=30)
        dst = sqlite3.connect(destination)
        try:
            src.execute("PRAGMA busy_timeout=30000")
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return destination

    def event(self, severity, event_type, message, *, account_key=None, group_id=None, campaign_id=None, details=None):
        with self.connect() as con:
            con.execute(
                "INSERT INTO events(created_at,severity,event_type,account_key,group_id,campaign_id,message,details) VALUES(?,?,?,?,?,?,?,?)",
                (utcnow(), severity, event_type, account_key, group_id, campaign_id, redact_text(message), redact_text(details)),
            )

    def audit(self, actor: str, action: str, *, target_type: str | None = None, target_id: str | None = None, details: str | None = None):
        with self.connect() as con:
            con.execute(
                "INSERT INTO audit_log(created_at,actor,action,target_type,target_id,details) VALUES(?,?,?,?,?,?)",
                (utcnow(), redact_text(actor) or "unknown", action, target_type, target_id, redact_text(details)),
            )

    def heartbeat(self, component: str, status: str = "ok", details: str | None = None):
        now = utcnow()
        with self.connect() as con:
            con.execute('''INSERT INTO heartbeats(component,last_seen_at,status,details) VALUES(?,?,?,?)
                           ON CONFLICT(component) DO UPDATE SET last_seen_at=excluded.last_seen_at,status=excluded.status,details=excluded.details''',
                        (component, now, status, details))
        return now
