from __future__ import annotations

SCHEMA_VERSION = 3

def ensure_v3_schema(store) -> None:
    with store.connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS bot_metrics(
            metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
            bucket_utc TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            source TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL,
            unit TEXT,
            quality TEXT NOT NULL DEFAULT 'observed',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(source, metric, bucket_utc)
        );
        CREATE INDEX IF NOT EXISTS idx_bot_metrics_source_metric_time
            ON bot_metrics(source, metric, observed_at_utc);

        CREATE TABLE IF NOT EXISTS root_cause_reports(
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL UNIQUE,
            incident_id INTEGER,
            source TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            confidence REAL NOT NULL,
            probable_cause TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS automation_opportunities(
            opportunity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            rationale TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS operational_goals(
            goal_id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_key TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            metric TEXT NOT NULL,
            operator TEXT NOT NULL,
            target REAL NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            title TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS goal_evaluations(
            evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_key TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            actual REAL,
            target REAL NOT NULL,
            status TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_goal_eval_key_time
            ON goal_evaluations(goal_key, observed_at_utc);

        CREATE TABLE IF NOT EXISTS release_events(
            release_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            detected_at_utc TEXT NOT NULL,
            previous_version TEXT,
            version TEXT,
            previous_hash TEXT,
            source_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'observing',
            baseline_score REAL,
            evaluated_score REAL,
            notes TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS notification_state(
            state_key TEXT PRIMARY KEY,
            state_value TEXT,
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS intelligence_cycles(
            cycle_id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at_utc TEXT NOT NULL,
            completed_at_utc TEXT NOT NULL,
            duration_ms REAL NOT NULL,
            ingested_events INTEGER NOT NULL DEFAULT 0,
            metric_sources INTEGER NOT NULL DEFAULT 0,
            incident_count INTEGER NOT NULL DEFAULT 0,
            action_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS config_baselines(
            config_key TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            first_seen_utc TEXT NOT NULL,
            last_seen_utc TEXT NOT NULL,
            last_changed_utc TEXT
        );

        CREATE TABLE IF NOT EXISTS postmortems(
            postmortem_id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL UNIQUE,
            generated_at_utc TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            probable_cause TEXT,
            impact TEXT,
            recovery TEXT,
            prevention TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS test_proposals(
            proposal_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            incident_id INTEGER,
            title TEXT NOT NULL,
            rationale TEXT NOT NULL,
            suggested_test TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed',
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS intelligence_feedback(
            feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER,
            verdict TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            created_at_utc TEXT NOT NULL
        );
        """)
        con.execute(
            "INSERT OR REPLACE INTO intelligence_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
