from __future__ import annotations

SCHEMA_VERSION = 4


def ensure_v4_schema(store) -> None:
    # v4 is an additive migration and is safe to call directly on v2/v3 databases.
    from .integrated_schema import ensure_v3_schema
    ensure_v3_schema(store)
    with store.connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_registry(
                service TEXT PRIMARY KEY,
                runtime_id TEXT NOT NULL UNIQUE,
                canonical_root TEXT NOT NULL,
                canonical_entrypoint TEXT NOT NULL,
                compatibility_entrypoint TEXT,
                manifest_path TEXT,
                version TEXT,
                managed INTEGER NOT NULL DEFAULT 0,
                auto_start INTEGER NOT NULL DEFAULT 0,
                auto_restart INTEGER NOT NULL DEFAULT 0,
                discovery_confidence REAL NOT NULL DEFAULT 0,
                source_hash TEXT,
                topology_hash TEXT,
                status TEXT NOT NULL DEFAULT 'observed',
                observed_at_utc TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS architecture_violations(
                violation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                service TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                first_seen_utc TEXT NOT NULL,
                last_seen_utc TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_architecture_violations_status
                ON architecture_violations(status,severity,service);

            CREATE TABLE IF NOT EXISTS slo_definitions(
                slo_key TEXT PRIMARY KEY,
                service TEXT NOT NULL,
                metric TEXT NOT NULL,
                operator TEXT NOT NULL,
                target REAL NOT NULL,
                window_hours INTEGER NOT NULL DEFAULT 24,
                error_budget REAL NOT NULL DEFAULT 0,
                title TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT 'default',
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS slo_evaluations(
                evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                slo_key TEXT NOT NULL,
                observed_at_utc TEXT NOT NULL,
                actual REAL,
                target REAL NOT NULL,
                status TEXT NOT NULL,
                error_budget_remaining REAL,
                details TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_slo_eval_key_time
                ON slo_evaluations(slo_key,observed_at_utc);

            CREATE TABLE IF NOT EXISTS operational_objectives(
                objective_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 50,
                enabled INTEGER NOT NULL DEFAULT 1,
                autonomy_ceiling INTEGER NOT NULL DEFAULT 4,
                guardrails_json TEXT NOT NULL DEFAULT '{}',
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS objective_evaluations(
                evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                objective_key TEXT NOT NULL,
                observed_at_utc TEXT NOT NULL,
                score REAL,
                status TEXT NOT NULL,
                plan_json TEXT NOT NULL DEFAULT '[]',
                evidence_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_objective_eval_key_time
                ON objective_evaluations(objective_key,observed_at_utc);

            CREATE TABLE IF NOT EXISTS autonomy_state(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                level INTEGER NOT NULL DEFAULT 4,
                mode TEXT NOT NULL DEFAULT 'recover',
                freeze_until_utc TEXT,
                reason TEXT NOT NULL DEFAULT '',
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS action_registry(
                action_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                minimum_level INTEGER NOT NULL,
                maximum_risk TEXT NOT NULL,
                reversible INTEGER NOT NULL,
                requires_backup INTEGER NOT NULL DEFAULT 0,
                cooldown_seconds INTEGER NOT NULL DEFAULT 0,
                capability TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS runbook_executions(
                execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
                runbook_key TEXT NOT NULL,
                service TEXT,
                started_at_utc TEXT NOT NULL,
                completed_at_utc TEXT,
                outcome TEXT NOT NULL DEFAULT 'running',
                confidence REAL,
                steps_json TEXT NOT NULL DEFAULT '[]',
                evidence_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS dependency_edges(
                edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                observed_at_utc TEXT NOT NULL,
                UNIQUE(source,target,edge_type)
            );

            CREATE TABLE IF NOT EXISTS release_acceptance(
                release_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                version TEXT,
                evaluated_at_utc TEXT NOT NULL,
                baseline_score REAL,
                candidate_score REAL,
                score_delta REAL,
                critical_incidents INTEGER NOT NULL DEFAULT 0,
                slo_breaches INTEGER NOT NULL DEFAULT 0,
                decision TEXT NOT NULL,
                reasons_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS attention_metrics(
                bucket_date TEXT PRIMARY KEY,
                notifications_sent INTEGER NOT NULL DEFAULT 0,
                useful_notifications INTEGER NOT NULL DEFAULT 0,
                noise_notifications INTEGER NOT NULL DEFAULT 0,
                approvals_requested INTEGER NOT NULL DEFAULT 0,
                manual_interventions INTEGER NOT NULL DEFAULT 0,
                autonomous_recoveries INTEGER NOT NULL DEFAULT 0,
                estimated_minutes_saved REAL NOT NULL DEFAULT 0,
                updated_at_utc TEXT NOT NULL
            );
            """
        )
        con.execute(
            "INSERT OR REPLACE INTO intelligence_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
