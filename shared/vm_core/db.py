from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from datetime import datetime, timezone
from typing import Iterator, Any
from .paths import project_root

SCHEMA_VERSION = 1

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
                created_at_utc TEXT NOT NULL
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
            con.execute(
                "INSERT OR IGNORE INTO migrations(version, applied_at_utc, description) VALUES(?,?,?)",
                (1, utcnow(), "Initial VM Platform schema"),
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

    def add_event(self, event_type: str, source: str, payload: dict[str, Any] | None = None) -> int:
        with self.connect() as con:
            cur = con.execute(
                "INSERT INTO events(event_type,source,payload_json,created_at_utc) VALUES(?,?,?,?)",
                (event_type, source, json.dumps(payload or {}, ensure_ascii=False), utcnow()),
            )
            return int(cur.lastrowid)

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (max(1, limit),)
            )]

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
