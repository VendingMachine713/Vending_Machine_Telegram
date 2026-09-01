from __future__ import annotations
SCHEMA_VERSION=12

def ensure_v6_schema(store):
    from .v5_schema import ensure_v5_schema
    ensure_v5_schema(store)
    with store.connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS evidence_records(
          evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, claim_key TEXT NOT NULL, observed_at_utc TEXT NOT NULL,
          freshness_seconds REAL, quality TEXT NOT NULL, confidence REAL NOT NULL,
          provenance TEXT NOT NULL, value_json TEXT NOT NULL DEFAULT '{}', metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_claim ON evidence_records(claim_key,observed_at_utc);
        CREATE TABLE IF NOT EXISTS policy_decisions(
          policy_decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at_utc TEXT NOT NULL, action_key TEXT NOT NULL, capability TEXT NOT NULL,
          requested_level INTEGER NOT NULL, effective_level INTEGER NOT NULL, decision TEXT NOT NULL,
          risk TEXT NOT NULL, evidence_quality REAL NOT NULL, rollback_ready INTEGER NOT NULL,
          backup_ready INTEGER NOT NULL, security_score REAL, reliability_freeze INTEGER NOT NULL,
          reasons_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS intervention_outcomes(
          intervention_id INTEGER PRIMARY KEY AUTOINCREMENT,
          action_key TEXT NOT NULL, source TEXT NOT NULL, started_at_utc TEXT NOT NULL,
          completed_at_utc TEXT, immediate_success INTEGER, recurrence_24h INTEGER,
          recurrence_7d INTEGER, root_cause_success INTEGER, attention_saved_minutes REAL DEFAULT 0,
          outcome TEXT, evidence_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS runbook_revisions(
          revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
          runbook_key TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
          generated_at_utc TEXT NOT NULL, parent_revision_id INTEGER, trust_score REAL NOT NULL DEFAULT 0,
          simulation_status TEXT NOT NULL DEFAULT 'pending', shadow_status TEXT NOT NULL DEFAULT 'pending',
          definition_json TEXT NOT NULL DEFAULT '{}', evidence_json TEXT NOT NULL DEFAULT '{}',
          UNIQUE(runbook_key,version)
        );
        CREATE TABLE IF NOT EXISTS prediction_outcomes(
          prediction_id INTEGER PRIMARY KEY, evaluated_at_utc TEXT NOT NULL,
          classification TEXT NOT NULL, calibrated_probability REAL,
          actual_event INTEGER, brier_score REAL, metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS attention_events(
          attention_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at_utc TEXT NOT NULL, event_type TEXT NOT NULL, source TEXT NOT NULL,
          cost_units REAL NOT NULL, useful INTEGER, avoided INTEGER NOT NULL DEFAULT 0,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS disaster_recovery_drills(
          drill_id INTEGER PRIMARY KEY AUTOINCREMENT,
          started_at_utc TEXT NOT NULL, completed_at_utc TEXT, mode TEXT NOT NULL,
          backup_age_minutes REAL, rpo_minutes REAL, rto_seconds REAL, integrity_ok INTEGER,
          restore_verified INTEGER, confidence REAL NOT NULL DEFAULT 0, outcome TEXT NOT NULL,
          evidence_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS architecture_modernization_candidates(
          candidate_key TEXT PRIMARY KEY, title TEXT NOT NULL, created_at_utc TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'proposal', impact REAL NOT NULL DEFAULT 0,
          risk REAL NOT NULL DEFAULT 0, confidence REAL NOT NULL DEFAULT 0,
          isolated_only INTEGER NOT NULL DEFAULT 1, production_mutation INTEGER NOT NULL DEFAULT 0,
          plan_json TEXT NOT NULL DEFAULT '{}', evidence_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS strategic_horizons(
          horizon_key TEXT PRIMARY KEY, generated_at_utc TEXT NOT NULL,
          hours INTEGER NOT NULL, plan_json TEXT NOT NULL DEFAULT '[]'
        );
        """)
        con.execute("INSERT OR REPLACE INTO intelligence_meta(key,value) VALUES('schema_version',?)",(str(SCHEMA_VERSION),))
