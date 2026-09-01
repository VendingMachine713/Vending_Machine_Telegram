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









CREATE TABLE IF NOT EXISTS app_meta (
    meta_key TEXT PRIMARY KEY,
    meta_value TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_views (
    admin_id INTEGER NOT NULL,
    view_name TEXT NOT NULL,
    query_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (admin_id, view_name)
);

CREATE TABLE IF NOT EXISTS integration_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'relationship_manager',
    event_type TEXT NOT NULL,
    telegram_id INTEGER,
    payload_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    exported_at TEXT
);

CREATE TABLE IF NOT EXISTS contact_controls (
    telegram_id INTEGER PRIMARY KEY,
    archived INTEGER NOT NULL DEFAULT 0,
    excluded INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS milestone_markers (
    telegram_id INTEGER NOT NULL,
    marker_key TEXT NOT NULL,
    marker_value TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (telegram_id, marker_key),
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'lead',
    status TEXT NOT NULL DEFAULT 'open',
    value_cents INTEGER,
    currency TEXT NOT NULL DEFAULT 'AUD',
    probability INTEGER NOT NULL DEFAULT 10,
    next_action TEXT,
    due_at TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS network_metrics (
    telegram_id INTEGER PRIMARY KEY,
    shared_groups INTEGER NOT NULL DEFAULT 0,
    active_groups_30 INTEGER NOT NULL DEFAULT 0,
    known_neighbors INTEGER NOT NULL DEFAULT 0,
    reach_score INTEGER NOT NULL DEFAULT 0,
    bridge_score INTEGER NOT NULL DEFAULT 0,
    diversity_score INTEGER NOT NULL DEFAULT 0,
    network_label TEXT NOT NULL DEFAULT 'learning',
    computed_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS private_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('incoming','outgoing')),
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(chat_id, message_id, direction),
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS behavior_metrics (
    telegram_id INTEGER PRIMARY KEY,
    incoming_30 INTEGER NOT NULL DEFAULT 0,
    outgoing_30 INTEGER NOT NULL DEFAULT 0,
    incoming_initiations_60 INTEGER NOT NULL DEFAULT 0,
    outgoing_initiations_60 INTEGER NOT NULL DEFAULT 0,
    reciprocity_score INTEGER NOT NULL DEFAULT 50,
    consistency_score INTEGER NOT NULL DEFAULT 0,
    median_our_response_seconds REAL,
    median_their_response_seconds REAL,
    our_response_samples INTEGER NOT NULL DEFAULT 0,
    their_response_samples INTEGER NOT NULL DEFAULT 0,
    acceleration_pct REAL NOT NULL DEFAULT 0,
    behavior_label TEXT NOT NULL DEFAULT 'learning',
    computed_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
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


CREATE TABLE IF NOT EXISTS contact_priorities (
    telegram_id INTEGER PRIMARY KEY,
    priority_score INTEGER NOT NULL DEFAULT 0,
    priority_band TEXT NOT NULL DEFAULT 'watch',
    reason_json TEXT NOT NULL DEFAULT '[]',
    next_action TEXT,
    snoozed_until TEXT,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relationship_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT 'custom',
    memory_key TEXT NOT NULL,
    memory_value TEXT NOT NULL,
    confidence INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'active',
    created_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS group_daily_activity (
    chat_id INTEGER NOT NULL,
    activity_date TEXT NOT NULL,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, activity_date)
);
CREATE INDEX IF NOT EXISTS idx_group_daily_activity ON group_daily_activity(chat_id, activity_date);

CREATE TABLE IF NOT EXISTS group_metrics (
    chat_id INTEGER PRIMARY KEY,
    chat_title TEXT,
    known_contacts INTEGER NOT NULL DEFAULT 0,
    active_contacts_30 INTEGER NOT NULL DEFAULT 0,
    interactions_30 INTEGER NOT NULL DEFAULT 0,
    vip_contacts INTEGER NOT NULL DEFAULT 0,
    commercial_contacts INTEGER NOT NULL DEFAULT 0,
    bridge_contacts INTEGER NOT NULL DEFAULT 0,
    avg_relationship_score REAL NOT NULL DEFAULT 0,
    group_value_score INTEGER NOT NULL DEFAULT 0,
    computed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backup_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    integrity_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS relationship_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    goal_type TEXT NOT NULL DEFAULT 'relationship',
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    priority INTEGER NOT NULL DEFAULT 50,
    target_at TEXT,
    next_step TEXT,
    progress_pct INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contact_segments (
    telegram_id INTEGER NOT NULL,
    segment_key TEXT NOT NULL,
    confidence INTEGER NOT NULL DEFAULT 50,
    reason TEXT,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (telegram_id, segment_key),
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversation_session_metrics (
    telegram_id INTEGER PRIMARY KEY,
    sessions_30 INTEGER NOT NULL DEFAULT 0,
    avg_messages_per_session REAL NOT NULL DEFAULT 0,
    median_duration_seconds INTEGER NOT NULL DEFAULT 0,
    incoming_started_30 INTEGER NOT NULL DEFAULT 0,
    outgoing_started_30 INTEGER NOT NULL DEFAULT 0,
    initiation_balance_score INTEGER NOT NULL DEFAULT 50,
    session_label TEXT NOT NULL DEFAULT 'learning',
    computed_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contact_forecasts (
    telegram_id INTEGER PRIMARY KEY,
    disengagement_risk INTEGER NOT NULL DEFAULT 20,
    reengagement_priority INTEGER NOT NULL DEFAULT 0,
    outlook_label TEXT NOT NULL DEFAULT 'learning',
    confidence INTEGER NOT NULL DEFAULT 20,
    reason_json TEXT NOT NULL DEFAULT '[]',
    computed_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS data_quality_metrics (
    telegram_id INTEGER PRIMARY KEY,
    completeness_score INTEGER NOT NULL DEFAULT 0,
    confidence_score INTEGER NOT NULL DEFAULT 20,
    missing_fields_json TEXT NOT NULL DEFAULT '[]',
    computed_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS brief_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_type TEXT NOT NULL DEFAULT 'daily',
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS contact_classifications (
    telegram_id INTEGER PRIMARY KEY,
    predicted_type TEXT NOT NULL DEFAULT 'unknown',
    confidence INTEGER NOT NULL DEFAULT 0,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    decision_state TEXT NOT NULL DEFAULT 'abstained',
    auto_applied INTEGER NOT NULL DEFAULT 0,
    admin_locked INTEGER NOT NULL DEFAULT 0,
    previous_type TEXT,
    computed_at TEXT NOT NULL,
    applied_at TEXT,
    reviewed_at TEXT,
    reviewed_by INTEGER,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS classification_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    predicted_type TEXT,
    confidence INTEGER NOT NULL DEFAULT 0,
    final_type TEXT,
    outcome TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'admin',
    details TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recommended_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    action_key TEXT NOT NULL,
    title TEXT NOT NULL,
    reason TEXT,
    action_score INTEGER NOT NULL DEFAULT 0,
    confidence INTEGER NOT NULL DEFAULT 50,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    due_at TEXT,
    snoozed_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS autonomy_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    old_mode TEXT,
    new_mode TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS maintenance_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    findings_before TEXT NOT NULL DEFAULT '[]',
    actions_json TEXT NOT NULL DEFAULT '[]',
    findings_after TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_classification_state ON contact_classifications(decision_state, confidence, predicted_type);
CREATE INDEX IF NOT EXISTS idx_classification_feedback ON classification_feedback(telegram_id, created_at);
CREATE INDEX IF NOT EXISTS idx_recommended_actions ON recommended_actions(status, action_score, confidence, snoozed_until);
CREATE INDEX IF NOT EXISTS idx_recommended_contact ON recommended_actions(telegram_id, status, action_score);
CREATE INDEX IF NOT EXISTS idx_maintenance_runs ON maintenance_runs(status, created_at);


CREATE TABLE IF NOT EXISTS classifier_calibration (
    relationship_type TEXT PRIMARY KEY,
    sample_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    overridden_count INTEGER NOT NULL DEFAULT 0,
    observed_precision REAL,
    effective_threshold INTEGER NOT NULL DEFAULT 85,
    auto_enabled INTEGER NOT NULL DEFAULT 1,
    reason TEXT,
    computed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER,
    telegram_id INTEGER NOT NULL,
    action_key TEXT NOT NULL,
    source TEXT NOT NULL,
    outcome TEXT NOT NULL,
    action_score INTEGER NOT NULL DEFAULT 0,
    details TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS operations_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    health_score INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    components_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_classifier_calibration ON classifier_calibration(auto_enabled, effective_threshold, sample_count);
CREATE INDEX IF NOT EXISTS idx_action_feedback ON action_feedback(telegram_id, action_key, outcome, created_at);
CREATE INDEX IF NOT EXISTS idx_operations_snapshots ON operations_snapshots(created_at, status, health_score);

CREATE INDEX IF NOT EXISTS idx_goals_status_due ON relationship_goals(status, target_at, priority);
CREATE INDEX IF NOT EXISTS idx_segments_key ON contact_segments(segment_key, confidence);
CREATE INDEX IF NOT EXISTS idx_forecasts_risk ON contact_forecasts(disengagement_risk, reengagement_priority);
CREATE INDEX IF NOT EXISTS idx_quality_confidence ON data_quality_metrics(confidence_score, completeness_score);

CREATE INDEX IF NOT EXISTS idx_priority_score ON contact_priorities(priority_score, priority_band);
CREATE INDEX IF NOT EXISTS idx_memory_contact ON relationship_memories(telegram_id, status, category);
CREATE INDEX IF NOT EXISTS idx_group_value ON group_metrics(group_value_score, active_contacts_30);
CREATE INDEX IF NOT EXISTS idx_reports_type ON report_snapshots(report_type, created_at);

CREATE INDEX IF NOT EXISTS idx_contacts_username ON contacts(username);
CREATE INDEX IF NOT EXISTS idx_contacts_last_seen ON contacts(last_seen);
CREATE INDEX IF NOT EXISTS idx_events_contact ON relationship_events(telegram_id, created_at);
CREATE INDEX IF NOT EXISTS idx_followups_due ON followups(status, due_at);
CREATE INDEX IF NOT EXISTS idx_attention_open ON attention_queue(status, priority);
CREATE INDEX IF NOT EXISTS idx_integration_events ON integration_events(status, created_at);
CREATE INDEX IF NOT EXISTS idx_contact_controls ON contact_controls(excluded, archived);
CREATE INDEX IF NOT EXISTS idx_opportunities_stage ON opportunities(status, stage, due_at);
CREATE INDEX IF NOT EXISTS idx_network_reach ON network_metrics(reach_score, bridge_score);
CREATE INDEX IF NOT EXISTS idx_private_interactions_contact_time ON private_interactions(telegram_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_behavior_label ON behavior_metrics(behavior_label, reciprocity_score);
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
            self._ensure_column(con, "integration_events", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(con, "integration_events", "last_error", "TEXT")
            self._ensure_column(con, "integration_events", "next_attempt_at", "TEXT")
            self._ensure_column(con, "opportunities", "health_score", "INTEGER NOT NULL DEFAULT 100")
            self._ensure_column(con, "opportunities", "stale_days", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(con, "recommended_actions", "cooldown_until", "TEXT")
            self._ensure_column(con, "recommended_actions", "occurrence_count", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(con, "recommended_actions", "last_present_at", "TEXT")
            self._ensure_column(con, "integration_events", "event_uuid", "TEXT")
            self._ensure_column(con, "integration_events", "event_version", "TEXT NOT NULL DEFAULT '1'")
            self._ensure_column(con, "integration_events", "dedupe_key", "TEXT")
            self._ensure_column(con, "integration_events", "priority", "INTEGER NOT NULL DEFAULT 50")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_integration_dedupe ON integration_events(dedupe_key) WHERE dedupe_key IS NOT NULL")
            con.execute(
                """INSERT INTO app_meta(meta_key,meta_value,updated_at) VALUES ('schema_version','6.0.0',?)
                   ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value,updated_at=excluded.updated_at""",
                (utcnow(),),
            )

    @staticmethod
    def _ensure_column(con, table: str, column: str, definition: str):
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def integrity_check(self):
        with self.connect() as con:
            rows = con.execute("PRAGMA integrity_check").fetchall()
            return [r[0] for r in rows]

    def table_exists(self, name: str) -> bool:
        row = self.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
        return bool(row)

    def meta(self, key: str, default=None):
        row = self.one("SELECT meta_value FROM app_meta WHERE meta_key=?", (key,))
        return row["meta_value"] if row else default

    def set_meta(self, key: str, value: str):
        self.execute(
            """INSERT INTO app_meta(meta_key,meta_value,updated_at) VALUES (?,?,?)
               ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value,updated_at=excluded.updated_at""",
            (key, str(value), utcnow()),
        )

    def checkpoint(self, truncate: bool = False):
        with self.connect() as con:
            mode = "TRUNCATE" if truncate else "PASSIVE"
            return con.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()

    def optimize(self):
        with self.connect() as con:
            con.execute("PRAGMA optimize")

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
