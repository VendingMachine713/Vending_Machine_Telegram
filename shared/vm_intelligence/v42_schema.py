from __future__ import annotations

SCHEMA_VERSION = 5

def ensure_v42_schema(store) -> None:
    from .v4_schema import ensure_v4_schema
    ensure_v4_schema(store)
    with store.connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS platform_services(
            service TEXT PRIMARY KEY,
            runtime_id TEXT NOT NULL UNIQUE,
            canonical_root TEXT NOT NULL,
            canonical_entrypoint TEXT NOT NULL,
            compatibility_entrypoint TEXT,
            manifest_path TEXT,
            version TEXT,
            classification TEXT NOT NULL DEFAULT 'CANONICAL',
            managed INTEGER NOT NULL DEFAULT 0,
            auto_start INTEGER NOT NULL DEFAULT 0,
            auto_restart INTEGER NOT NULL DEFAULT 0,
            owner TEXT NOT NULL,
            health_provider TEXT NOT NULL,
            telemetry_provider TEXT NOT NULL,
            database_paths_json TEXT NOT NULL DEFAULT '[]',
            config_paths_json TEXT NOT NULL DEFAULT '[]',
            dependencies_json TEXT NOT NULL DEFAULT '[]',
            source_hash TEXT,
            topology_hash TEXT,
            last_verified_utc TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'observed',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS config_registry(
            config_key TEXT PRIMARY KEY,
            service TEXT NOT NULL,
            path TEXT NOT NULL,
            sha256 TEXT,
            role TEXT NOT NULL,
            secret_bearing INTEGER NOT NULL DEFAULT 0,
            exists_flag INTEGER NOT NULL DEFAULT 1,
            observed_at_utc TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_config_registry_service ON config_registry(service);

        CREATE TABLE IF NOT EXISTS platform_drift_snapshots(
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at_utc TEXT NOT NULL,
            score REAL NOT NULL,
            high_count INTEGER NOT NULL DEFAULT 0,
            medium_count INTEGER NOT NULL DEFAULT 0,
            low_count INTEGER NOT NULL DEFAULT 0,
            findings_json TEXT NOT NULL DEFAULT '[]',
            registry_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reliability_service_stats(
            service TEXT PRIMARY KEY,
            incidents_30d INTEGER NOT NULL DEFAULT 0,
            recurrences_30d INTEGER NOT NULL DEFAULT 0,
            mttr_seconds REAL,
            mtbf_seconds REAL,
            availability_pct REAL,
            slo_compliance_pct REAL,
            error_budget_health_pct REAL,
            runbook_trust_score REAL,
            updated_at_utc TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS runbook_trust(
            runbook_key TEXT PRIMARY KEY,
            attempts INTEGER NOT NULL DEFAULT 0,
            successes INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,
            success_rate REAL,
            median_duration_ms REAL,
            trust_score REAL NOT NULL DEFAULT 0,
            certification TEXT NOT NULL DEFAULT 'unproven',
            updated_at_utc TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS reliability_windows(
            window_key TEXT PRIMARY KEY,
            observed_at_utc TEXT NOT NULL,
            compliance_pct REAL,
            breaches INTEGER NOT NULL DEFAULT 0,
            exhausted_budgets INTEGER NOT NULL DEFAULT 0,
            burn_rate_max REAL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        """)
        con.execute(
            "INSERT OR REPLACE INTO intelligence_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
