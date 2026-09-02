from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from datetime import datetime, timezone
from typing import Iterator, Any
from .paths import project_root

SCHEMA_VERSION = 3


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlatformDB:
    def __init__(self, path: Path | None = None, root: Path | None = None):
        root = root or project_root()
        self.path = path or (root / "state" / "vm_platform.sqlite3")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA journal_mode=WAL")
            yield con
            con.commit()
        finally:
            con.close()

    @staticmethod
    def _ensure_column(con: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        cols = {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def init(self) -> None:
        with self.connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS services (
                name TEXT PRIMARY KEY,
                folder TEXT NOT NULL,
                entrypoint TEXT,
                launcher TEXT,
                pid INTEGER,
                runtime_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                last_start_utc TEXT,
                last_stop_utc TEXT,
                last_error TEXT,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS service_health (
                service TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                detail_json TEXT NOT NULL DEFAULT '{}',
                checked_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'QUEUED',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                last_error TEXT,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at_utc TEXT NOT NULL,
                event_version INTEGER NOT NULL DEFAULT 1,
                severity TEXT NOT NULL DEFAULT 'INFO',
                subject_type TEXT,
                subject_id TEXT,
                correlation_id TEXT,
                evidence_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_key TEXT NOT NULL UNIQUE,
                incident_type TEXT NOT NULL,
                source TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                subject_type TEXT,
                subject_id TEXT,
                summary TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                first_seen_utc TEXT NOT NULL,
                last_seen_utc TEXT NOT NULL,
                resolved_at_utc TEXT
            );

            CREATE TABLE IF NOT EXISTS intelligence_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_key TEXT NOT NULL UNIQUE,
                signal_type TEXT NOT NULL,
                subject_type TEXT,
                subject_id TEXT,
                score REAL NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                rationale TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS intelligence_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_key TEXT NOT NULL UNIQUE,
                recommendation_type TEXT NOT NULL,
                subject_type TEXT,
                subject_id TEXT,
                priority REAL NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'PROPOSED',
                action TEXT NOT NULL,
                rationale TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                rule_version INTEGER NOT NULL DEFAULT 1,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS destinations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT UNIQUE,
                title TEXT,
                username TEXT,
                entity_type TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                primary_access INTEGER,
                secondary_access INTEGER,
                source TEXT,
                last_seen_utc TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                telegram_user_id TEXT,
                session_path TEXT UNIQUE,
                authorized INTEGER,
                source TEXT,
                last_seen_utc TEXT,
                capabilities_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                manifest_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS migrations (
                version INTEGER PRIMARY KEY,
                applied_at_utc TEXT NOT NULL,
                description TEXT NOT NULL
            );
            """)
            for column, ddl in (
                ("event_version", "INTEGER NOT NULL DEFAULT 1"),
                ("severity", "TEXT NOT NULL DEFAULT 'INFO'"),
                ("subject_type", "TEXT"),
                ("subject_id", "TEXT"),
                ("correlation_id", "TEXT"),
                ("evidence_json", "TEXT NOT NULL DEFAULT '{}'")
            ):
                self._ensure_column(con, "events", column, ddl)

            con.executescript("""
            CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(event_type, created_at_utc);
            CREATE INDEX IF NOT EXISTS idx_events_subject ON events(subject_type, subject_id, created_at_utc);
            CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id);
            CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, severity, last_seen_utc);
            CREATE INDEX IF NOT EXISTS idx_signals_subject ON intelligence_signals(subject_type, subject_id, status);
            CREATE INDEX IF NOT EXISTS idx_recommendations_status ON intelligence_recommendations(status, priority, updated_at_utc);
            CREATE INDEX IF NOT EXISTS idx_recommendations_subject ON intelligence_recommendations(subject_type, subject_id, status);
            """)
            con.execute(
                "INSERT OR IGNORE INTO migrations(version, applied_at_utc, description) VALUES(?,?,?)",
                (1, utcnow(), "Initial VM Platform schema"),
            )
            con.execute(
                "INSERT OR IGNORE INTO migrations(version, applied_at_utc, description) VALUES(?,?,?)",
                (2, utcnow(), "Structured events, incidents and VM intelligence signals"),
            )
            con.execute(
                "INSERT OR IGNORE INTO migrations(version, applied_at_utc, description) VALUES(?,?,?)",
                (3, utcnow(), "Evidence-governed VM Intelligence recommendations"),
            )
            con.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )

    def integrity(self) -> str:
        if not self.path.exists():
            return "missing"
        with self.connect() as con:
            row = con.execute("PRAGMA integrity_check").fetchone()
            return row[0] if row else "no result"

    def upsert_service(self, name: str, folder: str, entrypoint: str | None, launcher: str | None) -> None:
        with self.connect() as con:
            con.execute("""
                INSERT INTO services(name, folder, entrypoint, launcher, updated_at_utc)
                VALUES(?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                  folder=excluded.folder,
                  entrypoint=excluded.entrypoint,
                  launcher=excluded.launcher,
                  updated_at_utc=excluded.updated_at_utc
            """, (name, folder, entrypoint, launcher, utcnow()))

    def set_service_runtime(self, name: str, status: str, pid: int | None = None,
                            error: str | None = None, started: bool = False,
                            stopped: bool = False) -> None:
        fields = ["runtime_status=?", "pid=?", "last_error=?", "updated_at_utc=?"]
        values: list[Any] = [status, pid, error, utcnow()]
        if started:
            fields.append("last_start_utc=?")
            values.append(utcnow())
        if stopped:
            fields.append("last_stop_utc=?")
            values.append(utcnow())
        values.append(name)
        with self.connect() as con:
            con.execute(f"UPDATE services SET {', '.join(fields)} WHERE name=?", values)

    def services(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM services ORDER BY name")]

    def add_event(self, event_type: str, source: str, payload: dict[str, Any] | None = None,
                  *, event_version: int = 1, severity: str = "INFO",
                  subject_type: str | None = None, subject_id: str | None = None,
                  correlation_id: str | None = None,
                  evidence: dict[str, Any] | None = None) -> int:
        with self.connect() as con:
            cur = con.execute("""
                INSERT INTO events(
                    event_type,source,payload_json,created_at_utc,event_version,severity,
                    subject_type,subject_id,correlation_id,evidence_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (
                event_type, source, json.dumps(payload or {}, ensure_ascii=False), utcnow(),
                int(event_version), severity.upper(), subject_type, subject_id, correlation_id,
                json.dumps(evidence or {}, ensure_ascii=False),
            ))
            return int(cur.lastrowid)

    def events(self, limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM events"
        params: list[Any] = []
        if event_type:
            query += " WHERE event_type=?"
            params.append(event_type)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, limit))
        with self.connect() as con:
            return [dict(r) for r in con.execute(query, params)]

    def upsert_incident(self, incident_key: str, incident_type: str, source: str,
                        severity: str, summary: str, *, subject_type: str | None = None,
                        subject_id: str | None = None,
                        evidence: dict[str, Any] | None = None) -> int:
        now = utcnow()
        with self.connect() as con:
            con.execute("""
                INSERT INTO incidents(
                    incident_key,incident_type,source,severity,status,subject_type,subject_id,
                    summary,evidence_json,first_seen_utc,last_seen_utc
                ) VALUES(?,?,?,?, 'OPEN',?,?,?,?,?,?)
                ON CONFLICT(incident_key) DO UPDATE SET
                    incident_type=excluded.incident_type,
                    source=excluded.source,
                    severity=excluded.severity,
                    status='OPEN',
                    subject_type=excluded.subject_type,
                    subject_id=excluded.subject_id,
                    summary=excluded.summary,
                    evidence_json=excluded.evidence_json,
                    last_seen_utc=excluded.last_seen_utc,
                    resolved_at_utc=NULL
            """, (
                incident_key, incident_type, source, severity.upper(), subject_type, subject_id,
                summary, json.dumps(evidence or {}, ensure_ascii=False), now, now,
            ))
            row = con.execute("SELECT id FROM incidents WHERE incident_key=?", (incident_key,)).fetchone()
            return int(row[0])

    def resolve_incident(self, incident_key: str) -> bool:
        now = utcnow()
        with self.connect() as con:
            cur = con.execute(
                "UPDATE incidents SET status='RESOLVED', resolved_at_utc=?, last_seen_utc=? WHERE incident_key=? AND status!='RESOLVED'",
                (now, now, incident_key),
            )
            return bool(cur.rowcount)

    def incidents(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM incidents"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status.upper())
        query += " ORDER BY CASE severity WHEN 'CRITICAL' THEN 4 WHEN 'ERROR' THEN 3 WHEN 'WARNING' THEN 2 ELSE 1 END DESC, last_seen_utc DESC LIMIT ?"
        params.append(max(1, limit))
        with self.connect() as con:
            return [dict(r) for r in con.execute(query, params)]

    def upsert_signal(self, signal_key: str, signal_type: str, rationale: str,
                      *, subject_type: str | None = None, subject_id: str | None = None,
                      score: float = 0, confidence: float = 0,
                      evidence: dict[str, Any] | None = None, status: str = "ACTIVE") -> int:
        now = utcnow()
        with self.connect() as con:
            con.execute("""
                INSERT INTO intelligence_signals(
                    signal_key,signal_type,subject_type,subject_id,score,confidence,status,
                    rationale,evidence_json,created_at_utc,updated_at_utc
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(signal_key) DO UPDATE SET
                    signal_type=excluded.signal_type,
                    subject_type=excluded.subject_type,
                    subject_id=excluded.subject_id,
                    score=excluded.score,
                    confidence=excluded.confidence,
                    status=excluded.status,
                    rationale=excluded.rationale,
                    evidence_json=excluded.evidence_json,
                    updated_at_utc=excluded.updated_at_utc
            """, (
                signal_key, signal_type, subject_type, subject_id, float(score), float(confidence),
                status.upper(), rationale, json.dumps(evidence or {}, ensure_ascii=False), now, now,
            ))
            row = con.execute("SELECT id FROM intelligence_signals WHERE signal_key=?", (signal_key,)).fetchone()
            return int(row[0])

    def signals(self, limit: int = 50, status: str | None = "ACTIVE") -> list[dict[str, Any]]:
        query = "SELECT * FROM intelligence_signals"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status.upper())
        query += " ORDER BY score DESC, confidence DESC, updated_at_utc DESC LIMIT ?"
        params.append(max(1, limit))
        with self.connect() as con:
            return [dict(r) for r in con.execute(query, params)]

    def upsert_recommendation(
        self, recommendation_key: str, recommendation_type: str, action: str, rationale: str,
        *, rule_id: str, rule_version: int = 1, subject_type: str | None = None,
        subject_id: str | None = None, priority: float = 0, confidence: float = 0,
        evidence: dict[str, Any] | None = None, status: str = "PROPOSED",
    ) -> int:
        """Create or refresh one explainable recommendation without duplicating it."""
        allowed = {"PROPOSED", "BLOCKED", "ACCEPTED", "DISMISSED", "COMPLETED", "EXPIRED"}
        normalized_status = status.upper()
        if normalized_status not in allowed:
            raise ValueError(f"unsupported recommendation status: {status}")
        now = utcnow()
        with self.connect() as con:
            con.execute("""
                INSERT INTO intelligence_recommendations(
                    recommendation_key,recommendation_type,subject_type,subject_id,
                    priority,confidence,status,action,rationale,rule_id,rule_version,
                    evidence_json,created_at_utc,updated_at_utc
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(recommendation_key) DO UPDATE SET
                    recommendation_type=excluded.recommendation_type,
                    subject_type=excluded.subject_type,
                    subject_id=excluded.subject_id,
                    priority=excluded.priority,
                    confidence=excluded.confidence,
                    status=CASE
                        WHEN intelligence_recommendations.status IN ('ACCEPTED','DISMISSED','COMPLETED')
                        THEN intelligence_recommendations.status ELSE excluded.status END,
                    action=excluded.action,
                    rationale=excluded.rationale,
                    rule_id=excluded.rule_id,
                    rule_version=excluded.rule_version,
                    evidence_json=excluded.evidence_json,
                    updated_at_utc=excluded.updated_at_utc
            """, (
                recommendation_key, recommendation_type, subject_type, subject_id,
                max(0.0, min(100.0, float(priority))),
                max(0.0, min(1.0, float(confidence))), normalized_status,
                action, rationale, rule_id, max(1, int(rule_version)),
                json.dumps(evidence or {}, ensure_ascii=False), now, now,
            ))
            row = con.execute(
                "SELECT id FROM intelligence_recommendations WHERE recommendation_key=?",
                (recommendation_key,),
            ).fetchone()
            return int(row[0])

    def recommendations(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM intelligence_recommendations"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status.upper())
        query += " ORDER BY priority DESC, confidence DESC, updated_at_utc DESC LIMIT ?"
        params.append(max(1, limit))
        with self.connect() as con:
            return [dict(r) for r in con.execute(query, params)]

    def add_job(self, job_type: str, payload: dict[str, Any] | None = None, max_attempts: int = 3) -> int:
        now = utcnow()
        with self.connect() as con:
            cur = con.execute("""
                INSERT INTO jobs(job_type,payload_json,status,attempts,max_attempts,created_at_utc,updated_at_utc)
                VALUES(?,?, 'QUEUED', 0, ?, ?, ?)
            """, (job_type, json.dumps(payload or {}, ensure_ascii=False), max_attempts, now, now))
            return int(cur.lastrowid)

    def jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (max(1, limit),)
            )]

    def set_health(self, service: str, status: str, detail: dict[str, Any]) -> None:
        with self.connect() as con:
            con.execute("""
                INSERT INTO service_health(service,status,detail_json,checked_at_utc)
                VALUES(?,?,?,?)
                ON CONFLICT(service) DO UPDATE SET
                    status=excluded.status,
                    detail_json=excluded.detail_json,
                    checked_at_utc=excluded.checked_at_utc
            """, (service, status, json.dumps(detail, ensure_ascii=False), utcnow()))
