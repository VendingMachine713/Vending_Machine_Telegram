from __future__ import annotations
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import json, sqlite3

from .metrics import MetricStore
from .lifecycle import effective_policy, all_effective_policies

def _utcnow():
    return datetime.now(timezone.utc)

def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except Exception:
        return None

def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None

def _read_env_value(path: Path, name: str):
    if not path.is_file():
        return None
    try:
        for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return None

def _resolve_db(bot_dir: Path, env_name: str, default: Path) -> Path:
    raw = _read_env_value(bot_dir / ".env", env_name)
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else (bot_dir / p).resolve()
    return default

@contextmanager
def _connect_ro(path: Path):
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        con.execute("PRAGMA busy_timeout=5000")
        yield con
    finally:
        con.close()

def _table(con, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

def _count(con, sql, args=()):
    row = con.execute(sql, args).fetchone()
    return int(row[0] or 0) if row else 0

@dataclass
class AdapterResult:
    source: str
    available: bool
    metrics: dict[str, float]
    evidence: dict[str, Any]
    quality: str = "observed"
    error: str | None = None

class SmartAutoPosterAdapter:
    source = "Smart_Auto_Poster_V2"
    def __init__(self, root: Path):
        self.root = root
        self.bot = root / "bots" / self.source

    def collect(self) -> AdapterResult:
        db = _resolve_db(self.bot, "DATABASE_PATH", self.bot / "data" / "smart_autoposter.sqlite3")
        if not db.is_file():
            return AdapterResult(self.source, False, {}, {"database": str(db)}, error="database_not_found")
        cutoff = (_utcnow() - timedelta(hours=24)).isoformat()
        metrics = {}
        evidence = {"database": str(db)}
        try:
            with _connect_ro(db) as con:
                if _table(con, "queue"):
                    rows = con.execute("SELECT status,COUNT(*) n FROM queue GROUP BY status").fetchall()
                    q = {str(r["status"]): int(r["n"]) for r in rows}
                    for k, v in q.items():
                        metrics[f"queue_{k}"] = v
                    sent = _count(con, "SELECT COUNT(*) FROM queue WHERE status='sent' AND updated_at>=?", (cutoff,))
                    failed = _count(con, "SELECT COUNT(*) FROM queue WHERE status IN ('failed','quarantined') AND updated_at>=?", (cutoff,))
                    denom = sent + failed
                    metrics["success_rate_24h"] = round((sent / denom) * 100, 2) if denom else 100.0
                    metrics["sent_24h"] = sent
                    metrics["failed_24h"] = failed
                    if "uncertain" in q:
                        metrics["uncertain_queue"] = q["uncertain"]
                    evidence["queue_status"] = q
                    try:
                        errs = con.execute("""SELECT COALESCE(error_kind,'unknown') kind,COUNT(*) n
                            FROM queue WHERE updated_at>=? AND status IN ('failed','quarantined','uncertain')
                            GROUP BY COALESCE(error_kind,'unknown') ORDER BY n DESC LIMIT 5""", (cutoff,)).fetchall()
                        evidence["top_error_kinds"] = [{"kind": r["kind"], "count": int(r["n"])} for r in errs]
                    except Exception:
                        pass
                if _table(con, "accounts"):
                    rows = con.execute("SELECT enabled,authorized,health_score,consecutive_failures,cooldown_until FROM accounts").fetchall()
                    metrics["accounts_total"] = len(rows)
                    metrics["accounts_authorized"] = sum(1 for r in rows if r["authorized"])
                    metrics["accounts_enabled"] = sum(1 for r in rows if r["enabled"])
                    vals = [float(r["health_score"]) for r in rows if r["health_score"] is not None]
                    metrics["account_health_avg"] = round(sum(vals)/len(vals),2) if vals else 0
                    metrics["account_failure_streaks"] = sum(int(r["consecutive_failures"] or 0) for r in rows)
                if _table(con, "campaigns"):
                    metrics["campaigns_active"] = _count(con, "SELECT COUNT(*) FROM campaigns WHERE enabled=1")
                if _table(con, "destinations"):
                    metrics["destinations_enabled"] = _count(con, "SELECT COUNT(*) FROM destinations WHERE enabled=1")
                    metrics["destinations_quarantined"] = _count(con, """SELECT COUNT(*) FROM destinations
                        WHERE quarantine_until IS NOT NULL AND quarantine_until>?""", (_utcnow().isoformat(),))
                if _table(con, "events"):
                    metrics["error_events_24h"] = _count(con, "SELECT COUNT(*) FROM events WHERE created_at>=? AND upper(severity)='ERROR'", (cutoff,))
                    metrics["warning_events_24h"] = _count(con, "SELECT COUNT(*) FROM events WHERE created_at>=? AND upper(severity)='WARNING'", (cutoff,))
                if _table(con, "recommendations"):
                    metrics["open_recommendations"] = _count(con, "SELECT COUNT(*) FROM recommendations WHERE status='open'")
                if _table(con, "heartbeats"):
                    rows = con.execute("SELECT component,last_seen_at,status FROM heartbeats").fetchall()
                    now = _utcnow()
                    ages = []
                    for r in rows:
                        dt = _parse_iso(r["last_seen_at"])
                        if dt:
                            ages.append(max(0, (now - dt).total_seconds()))
                    metrics["heartbeat_stale_seconds_max"] = round(max(ages),1) if ages else 0
            metrics["database_size_mib"] = round(db.stat().st_size / (1024*1024), 3)
            return AdapterResult(self.source, True, metrics, evidence)
        except Exception as exc:
            return AdapterResult(self.source, False, metrics, evidence, error=type(exc).__name__)

class RelationshipManagerAdapter:
    source = "VM_Relationship_Manager"
    def __init__(self, root: Path):
        self.root = root
        self.bot = root / "bots" / self.source

    def collect(self) -> AdapterResult:
        default = self.root / "shared" / "exports" / self.source / "vm_relationships.db"
        db = _resolve_db(self.bot, "DATABASE_PATH", default)
        if not db.is_file():
            return AdapterResult(self.source, False, {}, {"database": str(db)}, error="database_not_found")
        cutoff = (_utcnow() - timedelta(hours=24)).isoformat()
        now = _utcnow().isoformat()
        metrics = {}
        evidence = {"database": str(db)}
        try:
            with _connect_ro(db) as con:
                if _table(con, "contacts"):
                    metrics["contacts_total"] = _count(con, "SELECT COUNT(*) FROM contacts")
                    metrics["contacts_active_30d"] = _count(con, "SELECT COUNT(*) FROM contacts WHERE last_seen>=?", ((_utcnow()-timedelta(days=30)).isoformat(),))
                if _table(con, "followups"):
                    metrics["followups_open"] = _count(con, "SELECT COUNT(*) FROM followups WHERE status='open'")
                    metrics["followups_overdue"] = _count(con, "SELECT COUNT(*) FROM followups WHERE status='open' AND due_at<?", (now,))
                if _table(con, "risk_flags"):
                    metrics["risk_flags_pending"] = _count(con, "SELECT COUNT(*) FROM risk_flags WHERE review_status='pending'")
                if _table(con, "attention_queue"):
                    metrics["attention_open"] = _count(con, "SELECT COUNT(*) FROM attention_queue WHERE status='open'")
                if _table(con, "bot_health"):
                    metrics["health_errors_24h"] = _count(con, """SELECT COUNT(*) FROM bot_health
                        WHERE created_at>=? AND lower(status) IN ('error','failed','offline')""", (cutoff,))
                    recent = con.execute("""SELECT component,status,details,created_at FROM bot_health
                        ORDER BY id DESC LIMIT 10""").fetchall()
                    evidence["recent_health"] = [
                        {"component": r["component"], "status": r["status"], "created_at": r["created_at"]}
                        for r in recent
                    ]
                if _table(con, "recommended_actions"):
                    metrics["actions_open"] = _count(con, "SELECT COUNT(*) FROM recommended_actions WHERE status='open'")
                if _table(con, "relationship_goals"):
                    metrics["goals_active"] = _count(con, "SELECT COUNT(*) FROM relationship_goals WHERE status='active'")
                if _table(con, "contact_forecasts"):
                    metrics["high_disengagement_risk"] = _count(con, "SELECT COUNT(*) FROM contact_forecasts WHERE disengagement_risk>=70")
                if _table(con, "data_quality_metrics"):
                    row = con.execute("SELECT AVG(completeness_score),AVG(confidence_score) FROM data_quality_metrics").fetchone()
                    metrics["data_completeness_avg"] = round(float(row[0] or 0),2)
                    metrics["data_confidence_avg"] = round(float(row[1] or 0),2)
                if _table(con, "integration_events"):
                    metrics["integration_pending"] = _count(con, "SELECT COUNT(*) FROM integration_events WHERE status='pending'")
                if _table(con, "admin_audit"):
                    metrics["admin_actions_24h"] = _count(con, "SELECT COUNT(*) FROM admin_audit WHERE created_at>=?", (cutoff,))
                    repeated = con.execute("""SELECT action,COUNT(*) n FROM admin_audit WHERE created_at>=?
                        GROUP BY action HAVING COUNT(*)>=3 ORDER BY n DESC LIMIT 5""", (cutoff,)).fetchall()
                    evidence["repeated_admin_actions"] = [{"action": r["action"], "count": int(r["n"])} for r in repeated]
                if _table(con, "app_meta"):
                    row = con.execute("SELECT meta_value FROM app_meta WHERE meta_key='last_heartbeat'").fetchone()
                    if row:
                        dt = _parse_iso(row[0])
                        if dt:
                            metrics["heartbeat_age_seconds"] = round(max(0, (_utcnow()-dt).total_seconds()),1)
                if _table(con, "backup_audit"):
                    row = con.execute("SELECT integrity_status,created_at FROM backup_audit ORDER BY id DESC LIMIT 1").fetchone()
                    if row:
                        metrics["latest_backup_verified"] = 1 if str(row["integrity_status"]).lower() in {"verified","ok","pass","valid"} else 0
                        evidence["latest_backup_status"] = row["integrity_status"]
            metrics["database_size_mib"] = round(db.stat().st_size / (1024*1024), 3)
            return AdapterResult(self.source, True, metrics, evidence)
        except Exception as exc:
            return AdapterResult(self.source, False, metrics, evidence, error=type(exc).__name__)

class UniversalSearchAdapter:
    source = "Universal_Search"
    def __init__(self, root: Path):
        self.root = root
        self.bot = root / "bots" / self.source

    def _legacy_db(self):
        direct = self.bot / "data" / "universal_search.db"
        if direct.is_file():
            return direct
        found = sorted(self.bot.glob("**/data/universal_search.db"), key=lambda p: len(p.parts))
        return found[0] if found else direct

    def collect(self) -> AdapterResult:
        metrics = {}
        evidence = {}
        try:
            try:
                from shared.vm_core.search_index import SearchIndex
                stats = SearchIndex(self.root).stats()
                evidence["platform_index"] = stats
                if isinstance(stats, dict):
                    for key in ("documents","destinations","accounts"):
                        if isinstance(stats.get(key), (int,float)):
                            metrics[f"platform_{key}"] = stats[key]
            except Exception:
                pass
            db = self._legacy_db()
            evidence["legacy_database"] = str(db)
            if db.is_file():
                with _connect_ro(db) as con:
                    if _table(con, "indexed_messages"):
                        metrics["legacy_messages"] = _count(con, "SELECT COUNT(*) FROM indexed_messages")
                    if _table(con, "chats"):
                        metrics["legacy_chats"] = _count(con, "SELECT COUNT(*) FROM chats")
                    if _table(con, "senders"):
                        metrics["legacy_senders"] = _count(con, "SELECT COUNT(*) FROM senders")
                    if _table(con, "search_audit"):
                        cutoff = (_utcnow()-timedelta(hours=24)).isoformat()
                        metrics["searches_24h"] = _count(con, "SELECT COUNT(*) FROM search_audit WHERE created_utc>=?", (cutoff,))
                metrics["legacy_database_size_mib"] = round(db.stat().st_size/(1024*1024),3)
            return AdapterResult(self.source, bool(metrics), metrics, evidence,
                                 error=None if metrics else "no_metrics_available")
        except Exception as exc:
            return AdapterResult(self.source, False, metrics, evidence, error=type(exc).__name__)

class RuntimeAdapter:
    def __init__(self, root: Path, source: str):
        self.root = root
        self.source = source

    def _policy(self):
        return effective_policy(self.root, self.source)

    def collect(self) -> AdapterResult:
        path = self.root / "diagnostics" / "live_runtime.json"
        data = _read_json(path) or {}
        row = next((x for x in data.get("services", []) if x.get("name") == self.source), None)
        comp = (data.get("components") or {}).get(self.source) or {}
        policy = self._policy()
        metrics = {
            "auto_restart": 1 if policy.get("auto_restart") else 0,
            "auto_start": 1 if policy.get("auto_start") else 0,
        }
        evidence = {"policy": policy}
        bridge = _read_json(self.root / "diagnostics" / "runtime_bridge_status.json") or {}
        bridge_row = next((x for x in bridge.get("services", []) if x.get("bot") == self.source), None)
        effective_alive = bool(row.get("process_alive")) if row else False
        effective_pid = row.get("pid") if row else None
        if bridge_row:
            bstatus = bridge_row.get("status") or {}
            if bstatus.get("alive"):
                effective_alive = True
                effective_pid = bstatus.get("pid") or effective_pid
            evidence["runtime_bridge"] = {
                "desired_running": bridge_row.get("desired_running"),
                "action": bridge_row.get("action"),
                "alive": bool(bstatus.get("alive")),
                "pid": bstatus.get("pid"),
            }
        if row or bridge_row:
            metrics["process_alive"] = 1 if effective_alive else 0
            evidence["runtime"] = {
                "runtime_status": row.get("runtime_status") if row else ("RUNNING" if effective_alive else "UNKNOWN"),
                "process_alive": effective_alive,
                "pid": effective_pid,
            }
        if comp:
            age = comp.get("age_seconds")
            if isinstance(age, (int, float)):
                metrics["component_age_seconds"] = age
            legacy = comp.get("legacy_component") or {}
            if "alive" in legacy:
                metrics["legacy_alive"] = 1 if legacy.get("alive") else 0
            evidence["component"] = {
                "legacy_expected": comp.get("legacy_component_expected"),
                "legacy_alive": legacy.get("alive"),
                "age_seconds": comp.get("age_seconds"),
            }
        return AdapterResult(self.source, bool(row or comp or policy), metrics, evidence,
                             error=None if (row or comp or policy) else "runtime_not_found")

class PlatformAdapter:
    source = "VM_Platform"
    def __init__(self, root: Path):
        self.root = root

    def _policies(self, validation):
        services={"Admin_Command_Centre","Smart_Auto_Poster_V2","Universal_Search","VM_Guard","VM_Relationship_Manager"}
        services.update(str(row.get("service")) for row in validation.get("supervisor_actions",[]) if row.get("service"))
        return all_effective_policies(self.root, sorted(services))

    def collect(self) -> AdapterResult:
        metrics = {}
        evidence = {}
        val = _read_json(self.root / "diagnostics" / "full_validation.json") or {}
        regression = _read_json(self.root / "diagnostics" / "intelligence_regression.json") or {}
        policies = self._policies(val)
        if val:
            metrics["preflight_ok"] = 1 if val.get("preflight_ok") else 0
            metrics["bots_runnable"] = float(val.get("bots_runnable") or 0)
            evidence["advisory_failed_test_suites"] = list(val.get("advisory_failed_test_suites") or [])
            evidence["doctor_summary"] = val.get("doctor_summary") or {}
            evidence["supervisor_policies"] = policies
        # Prefer the most recent dedicated regression run for test-suite state while
        # preserving full-validation Doctor/preflight evidence.
        val_stamp=_parse_iso(val.get("completed_at_utc")) if val else None
        reg_stamp=_parse_iso(regression.get("completed_at_utc")) if regression else None
        use_reg=bool(regression and (not val_stamp or (reg_stamp and reg_stamp>=val_stamp)))
        test_source=regression if use_reg else val
        failed=list(test_source.get("failed_test_suites") or []) if test_source else []
        metrics["all_test_suites_ok"] = 1 if not failed else 0
        metrics["critical_tests_ok"] = 1 if not failed else 0
        evidence["failed_test_suites"] = failed
        evidence["test_status_source"] = "intelligence_regression" if use_reg else "full_validation"
        if regression:
            evidence["new_failed_test_suites"] = list(regression.get("new_failed_test_suites") or [])
        runtime = _read_json(self.root / "diagnostics" / "live_runtime.json") or {}
        services = runtime.get("services") or []
        bridge = _read_json(self.root / "diagnostics" / "runtime_bridge_status.json") or {}
        bridge_by = {str(x.get("bot")): x for x in bridge.get("services", []) if x.get("bot")}
        down = []
        intentionally_stopped = []
        service_names = {str(x.get("name")) for x in services if x.get("name")}
        service_names.update(bridge_by)
        for name in sorted(service_names):
            x = next((r for r in services if str(r.get("name")) == name), {})
            policy = policies.get(name) or {}
            alive = bool(x.get("process_alive"))
            brow = bridge_by.get(name) or {}
            if (brow.get("status") or {}).get("alive"):
                alive = True
            if policy.get("auto_restart") and not alive:
                down.append(name)
            elif not policy.get("auto_restart") and not alive:
                intentionally_stopped.append(name)
        evidence["runtime_bridge"] = bridge_by
        metrics["managed_services_down"] = len(down)
        metrics["non_managed_services_stopped"] = len(intentionally_stopped)
        evidence["managed_services_down"] = down
        evidence["intentionally_stopped"] = intentionally_stopped
        alerts = runtime.get("open_alerts") or []
        metrics["open_alerts"] = len(alerts)
        evidence["open_alerts"] = [
            {"id": x.get("id"), "severity": x.get("severity"), "source": x.get("source"),
             "title": x.get("title"), "detail": x.get("detail"), "status": x.get("status"),
             "first_seen_utc": x.get("first_seen_utc"), "last_seen_utc": x.get("last_seen_utc"),
             "occurrences": x.get("occurrences")}
            for x in alerts
        ]
        return AdapterResult(self.source, True, metrics, evidence)

class AdapterHub:
    def __init__(self, store, root: Path):
        self.store = store
        self.root = Path(root)
        self.metrics = MetricStore(store)
        self.adapters = [
            SmartAutoPosterAdapter(self.root),
            RelationshipManagerAdapter(self.root),
            UniversalSearchAdapter(self.root),
            RuntimeAdapter(self.root, "VM_Guard"),
            RuntimeAdapter(self.root, "Admin_Command_Centre"),
            PlatformAdapter(self.root),
        ]

    def collect(self):
        results = {}
        for adapter in self.adapters:
            try:
                result = adapter.collect()
            except Exception as exc:
                result = AdapterResult(getattr(adapter, "source", type(adapter).__name__), False, {}, {},
                                       error=type(exc).__name__)
            results[result.source] = {
                "available": result.available,
                "metrics": result.metrics,
                "evidence": result.evidence,
                "quality": result.quality,
                "error": result.error,
            }
            for name, value in result.metrics.items():
                try:
                    self.metrics.record(result.source, name, value, metadata={"available": result.available})
                except Exception:
                    pass
        return results
