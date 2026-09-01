from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable
import json, sqlite3, threading
from .events import Event, utc_now_iso

SCHEMA_VERSION = 2

class IntelligenceStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db_path, timeout=15)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA busy_timeout=15000")
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self):
        with self._lock, self.connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS intelligence_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
              event_id TEXT PRIMARY KEY,timestamp_utc TEXT NOT NULL,source TEXT NOT NULL,
              kind TEXT NOT NULL,action TEXT NOT NULL,outcome TEXT NOT NULL,level TEXT NOT NULL,
              duration_ms REAL,value REAL,metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp_utc);
            CREATE INDEX IF NOT EXISTS idx_events_source_time ON events(source,timestamp_utc);
            CREATE INDEX IF NOT EXISTS idx_events_action_time ON events(action,timestamp_utc);
            CREATE INDEX IF NOT EXISTS idx_events_outcome_time ON events(outcome,timestamp_utc);

            CREATE TABLE IF NOT EXISTS recommendations(
              recommendation_id INTEGER PRIMARY KEY AUTOINCREMENT,created_at_utc TEXT NOT NULL,
              source TEXT NOT NULL,category TEXT NOT NULL,severity TEXT NOT NULL,title TEXT NOT NULL,
              rationale TEXT NOT NULL,evidence_json TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'open',
              fingerprint TEXT NOT NULL,UNIQUE(fingerprint,status));

            CREATE TABLE IF NOT EXISTS experiments(
              experiment_id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,source TEXT NOT NULL,
              hypothesis TEXT NOT NULL,metric TEXT NOT NULL,baseline REAL,candidate REAL,
              result TEXT NOT NULL DEFAULT 'pending',created_at_utc TEXT NOT NULL,updated_at_utc TEXT NOT NULL,
              notes TEXT NOT NULL DEFAULT '');

            CREATE TABLE IF NOT EXISTS incidents(
              incident_id INTEGER PRIMARY KEY AUTOINCREMENT,fingerprint TEXT NOT NULL UNIQUE,
              source TEXT NOT NULL,category TEXT NOT NULL,severity TEXT NOT NULL,title TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'open',first_seen_utc TEXT NOT NULL,last_seen_utc TEXT NOT NULL,
              occurrences INTEGER NOT NULL DEFAULT 1,evidence_json TEXT NOT NULL DEFAULT '{}',
              resolution TEXT NOT NULL DEFAULT '');

            CREATE TABLE IF NOT EXISTS decisions(
              decision_id INTEGER PRIMARY KEY AUTOINCREMENT,created_at_utc TEXT NOT NULL,source TEXT NOT NULL,
              action TEXT NOT NULL,authority TEXT NOT NULL,risk TEXT NOT NULL,confidence REAL NOT NULL,
              reason TEXT NOT NULL,outcome TEXT NOT NULL DEFAULT 'not_executed',
              metadata_json TEXT NOT NULL DEFAULT '{}');

            CREATE TABLE IF NOT EXISTS improvements(
              improvement_id INTEGER PRIMARY KEY AUTOINCREMENT,created_at_utc TEXT NOT NULL,source TEXT NOT NULL,
              title TEXT NOT NULL,metric TEXT NOT NULL,before_value REAL,after_value REAL,delta REAL,
              status TEXT NOT NULL,evidence_json TEXT NOT NULL DEFAULT '{}',fingerprint TEXT NOT NULL UNIQUE);

            CREATE TABLE IF NOT EXISTS snapshots(
              snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,created_at_utc TEXT NOT NULL,kind TEXT NOT NULL,
              payload_json TEXT NOT NULL);

            CREATE TABLE IF NOT EXISTS release_baselines(
              source TEXT PRIMARY KEY,version TEXT,source_hash TEXT NOT NULL,observed_at_utc TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}');
            """)
            con.execute("INSERT OR REPLACE INTO intelligence_meta(key,value) VALUES('schema_version',?)",(str(SCHEMA_VERSION),))

    def add_event(self,event: Event) -> bool:
        r=event.to_record()
        with self._lock,self.connect() as con:
            cur=con.execute("""INSERT OR IGNORE INTO events(
              event_id,timestamp_utc,source,kind,action,outcome,level,duration_ms,value,metadata_json)
              VALUES(?,?,?,?,?,?,?,?,?,?)""",
              (r["event_id"],r["timestamp_utc"],r["source"],r["kind"],r["action"],r["outcome"],r["level"],
               r["duration_ms"],r["value"],r["metadata_json"]))
            return cur.rowcount > 0

    def add_events(self,events: Iterable[Event]) -> int:
        return sum(1 for e in events if self.add_event(e))

    def query_events(self,*,source=None,since_utc=None,limit=10000):
        sql="SELECT * FROM events WHERE 1=1"; args=[]
        if source: sql+=" AND source=?"; args.append(source)
        if since_utc: sql+=" AND timestamp_utc>=?"; args.append(since_utc)
        sql+=" ORDER BY timestamp_utc DESC LIMIT ?"; args.append(limit)
        with self.connect() as con:
            return [dict(r) for r in con.execute(sql,args).fetchall()]

    def upsert_recommendation(self,*,source,category,severity,title,rationale,evidence,fingerprint):
        with self._lock,self.connect() as con:
            con.execute("""INSERT OR IGNORE INTO recommendations(
              created_at_utc,source,category,severity,title,rationale,evidence_json,fingerprint)
              VALUES(?,?,?,?,?,?,?,?)""",
              (utc_now_iso(),source,category,severity,title,rationale,json.dumps(evidence,sort_keys=True,default=str),fingerprint))

    def open_recommendations(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""SELECT * FROM recommendations WHERE status='open' ORDER BY
              CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
              created_at_utc DESC""").fetchall()]

    def create_experiment(self,*,name,source,hypothesis,metric,baseline=None,candidate=None,notes=""):
        now=utc_now_iso()
        with self._lock,self.connect() as con:
            cur=con.execute("""INSERT INTO experiments(name,source,hypothesis,metric,baseline,candidate,created_at_utc,updated_at_utc,notes)
              VALUES(?,?,?,?,?,?,?,?,?)""",(name,source,hypothesis,metric,baseline,candidate,now,now,notes))
            return int(cur.lastrowid)

    def finish_experiment(self,experiment_id,*,result,candidate,notes=""):
        if result not in {"win","loss","neutral","invalid"}: raise ValueError("result must be win/loss/neutral/invalid")
        with self._lock,self.connect() as con:
            con.execute("UPDATE experiments SET result=?,candidate=?,updated_at_utc=?,notes=? WHERE experiment_id=?",
                        (result,candidate,utc_now_iso(),notes,experiment_id))

    def upsert_incident(self,*,fingerprint,source,category,severity,title,evidence):
        now=utc_now_iso()
        with self._lock,self.connect() as con:
            row=con.execute("SELECT incident_id,status FROM incidents WHERE fingerprint=?",(fingerprint,)).fetchone()
            payload=json.dumps(evidence,sort_keys=True,default=str)
            if row:
                con.execute("""UPDATE incidents SET status='open',last_seen_utc=?,occurrences=occurrences+1,
                  severity=?,title=?,evidence_json=? WHERE fingerprint=?""",(now,severity,title,payload,fingerprint))
                return int(row["incident_id"])
            cur=con.execute("""INSERT INTO incidents(
              fingerprint,source,category,severity,title,first_seen_utc,last_seen_utc,evidence_json)
              VALUES(?,?,?,?,?,?,?,?)""",(fingerprint,source,category,severity,title,now,now,payload))
            return int(cur.lastrowid)

    def resolve_absent_incidents(self,active_fingerprints:set[str]):
        with self._lock,self.connect() as con:
            rows=con.execute("SELECT fingerprint FROM incidents WHERE status='open'").fetchall()
            for r in rows:
                if r["fingerprint"] not in active_fingerprints:
                    con.execute("UPDATE incidents SET status='resolved',resolution=? WHERE fingerprint=?",
                                ("Condition no longer detected automatically.",r["fingerprint"]))

    def open_incidents(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""SELECT * FROM incidents WHERE status='open' ORDER BY
              CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,last_seen_utc DESC""").fetchall()]

    def record_decision(self,*,source,action,authority,risk,confidence,reason,outcome="not_executed",metadata=None):
        with self._lock,self.connect() as con:
            con.execute("""INSERT INTO decisions(created_at_utc,source,action,authority,risk,confidence,reason,outcome,metadata_json)
              VALUES(?,?,?,?,?,?,?,?,?)""",(utc_now_iso(),source,action,authority,risk,float(confidence),reason,outcome,
              json.dumps(metadata or {},sort_keys=True,default=str)))

    def add_improvement(self,*,source,title,metric,before_value,after_value,status,evidence,fingerprint):
        delta=None if before_value is None or after_value is None else round(after_value-before_value,12)
        with self._lock,self.connect() as con:
            con.execute("""INSERT OR IGNORE INTO improvements(
              created_at_utc,source,title,metric,before_value,after_value,delta,status,evidence_json,fingerprint)
              VALUES(?,?,?,?,?,?,?,?,?,?)""",(utc_now_iso(),source,title,metric,before_value,after_value,delta,status,
              json.dumps(evidence,sort_keys=True,default=str),fingerprint))

    def improvements(self,limit=100):
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM improvements ORDER BY created_at_utc DESC LIMIT ?",(limit,)).fetchall()]

    def add_snapshot(self,kind,payload):
        with self._lock,self.connect() as con:
            con.execute("INSERT INTO snapshots(created_at_utc,kind,payload_json) VALUES(?,?,?)",
                        (utc_now_iso(),kind,json.dumps(payload,sort_keys=True,default=str)))

    def prune_events(self,older_than_utc):
        with self._lock,self.connect() as con:
            return con.execute("DELETE FROM events WHERE timestamp_utc<?",(older_than_utc,)).rowcount
