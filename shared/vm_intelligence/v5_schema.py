from __future__ import annotations

SCHEMA_VERSION = 8

def ensure_v5_schema(store) -> None:
    from .v42_schema import ensure_v42_schema
    ensure_v42_schema(store)
    with store.connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS incident_timelines(
            timeline_id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER,
            source TEXT NOT NULL,
            event_time_utc TEXT NOT NULL,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            evidence_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_incident_timelines_incident ON incident_timelines(incident_id,event_time_utc);

        CREATE TABLE IF NOT EXISTS failure_families(
            family_key TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            incident_count INTEGER NOT NULL DEFAULT 0,
            recurrence_count INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0,
            root_cause_json TEXT NOT NULL DEFAULT '{}',
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS predictions(
            prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            metric TEXT NOT NULL,
            horizon_hours INTEGER NOT NULL,
            probability REAL,
            predicted_value REAL,
            status TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            created_at_utc TEXT NOT NULL,
            due_at_utc TEXT,
            resolved_at_utc TEXT,
            actual_value REAL,
            outcome TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_predictions_source_due ON predictions(source,due_at_utc);

        CREATE TABLE IF NOT EXISTS release_candidates(
            release_key TEXT PRIMARY KEY,
            risk_score REAL NOT NULL,
            confidence REAL NOT NULL,
            blast_radius_json TEXT NOT NULL DEFAULT '[]',
            selected_tests_json TEXT NOT NULL DEFAULT '[]',
            gate_status TEXT NOT NULL,
            baseline_json TEXT NOT NULL DEFAULT '{}',
            observed_json TEXT NOT NULL DEFAULT '{}',
            decision TEXT,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS automation_candidates(
            candidate_key TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            trigger_pattern TEXT NOT NULL,
            frequency INTEGER NOT NULL DEFAULT 0,
            estimated_minutes_saved REAL NOT NULL DEFAULT 0,
            reversibility REAL NOT NULL DEFAULT 0,
            risk TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'shadow',
            runbook_json TEXT NOT NULL DEFAULT '{}',
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS capability_trust(
            capability TEXT PRIMARY KEY,
            minimum_level INTEGER NOT NULL,
            maximum_level INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            successes INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,
            false_positive_actions INTEGER NOT NULL DEFAULT 0,
            rollback_count INTEGER NOT NULL DEFAULT 0,
            trust_score REAL NOT NULL DEFAULT 0,
            certification TEXT NOT NULL DEFAULT 'unproven',
            effective_level INTEGER NOT NULL DEFAULT 0,
            updated_at_utc TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS engineering_candidates(
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_key TEXT NOT NULL UNIQUE,
            issue_source TEXT,
            title TEXT NOT NULL,
            workspace TEXT,
            regression_test TEXT,
            patch_summary TEXT,
            targeted_status TEXT NOT NULL DEFAULT 'pending',
            full_status TEXT NOT NULL DEFAULT 'pending',
            security_status TEXT NOT NULL DEFAULT 'pending',
            production_mutation INTEGER NOT NULL DEFAULT 0,
            release_gate_status TEXT,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS strategic_backlog(
            backlog_key TEXT PRIMARY KEY,
            priority TEXT NOT NULL,
            objective_key TEXT,
            title TEXT NOT NULL,
            impact REAL NOT NULL DEFAULT 0,
            risk REAL NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0,
            effort REAL NOT NULL DEFAULT 0,
            expected_attention_saved REAL NOT NULL DEFAULT 0,
            expected_reliability_gain REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'planned',
            authority_required INTEGER NOT NULL DEFAULT 0,
            action_key TEXT,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS planner_runs(
            planner_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at_utc TEXT NOT NULL,
            objective_count INTEGER NOT NULL,
            backlog_count INTEGER NOT NULL,
            executable_count INTEGER NOT NULL,
            blocked_count INTEGER NOT NULL,
            north_star REAL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        """)
        con.execute(
            "INSERT OR REPLACE INTO intelligence_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
