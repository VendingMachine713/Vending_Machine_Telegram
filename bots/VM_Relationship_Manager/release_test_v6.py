from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from backup_manager import BackupManager
from database import Database, utcnow
from relationship_engine import RelationshipEngine
from startup_utils import pre_upgrade_backup
from instance_lock import SingleInstanceLock, AlreadyRunningError


def legacy_v5_db(path: Path):
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE app_meta(meta_key TEXT PRIMARY KEY,meta_value TEXT,updated_at TEXT NOT NULL);
            CREATE TABLE contacts(
                telegram_id INTEGER PRIMARY KEY,username TEXT,display_name TEXT,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,
                relationship_type TEXT NOT NULL DEFAULT 'unknown',activity_status TEXT NOT NULL DEFAULT 'new',
                verification_status TEXT NOT NULL DEFAULT 'unknown',manual_importance INTEGER NOT NULL DEFAULT 0,
                relationship_score INTEGER NOT NULL DEFAULT 0,trust_score INTEGER NOT NULL DEFAULT 50,
                interaction_count INTEGER NOT NULL DEFAULT 0,active_days INTEGER NOT NULL DEFAULT 0,typical_cycle_days REAL,
                last_score_update TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            );
            CREATE TABLE recommended_actions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,action_key TEXT NOT NULL,title TEXT NOT NULL,
                reason TEXT,action_score INTEGER NOT NULL DEFAULT 0,confidence INTEGER NOT NULL DEFAULT 50,source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',due_at TEXT,snoozed_until TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE TABLE integration_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT NOT NULL DEFAULT 'relationship_manager',event_type TEXT NOT NULL,
                telegram_id INTEGER,payload_json TEXT,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL,exported_at TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,last_error TEXT,next_attempt_at TEXT
            );
            """
        )
        con.execute("INSERT INTO app_meta VALUES ('schema_version','5.0.0',?)", (now,))
        con.execute(
            "INSERT INTO contacts(telegram_id,username,display_name,first_seen,last_seen,relationship_type,created_at,updated_at) VALUES (?,?,?,?,?,'regular',?,?)",
            (42, "legacy", "Legacy Contact", now, now, now, now),
        )
        con.execute(
            "INSERT INTO recommended_actions(telegram_id,action_key,title,action_score,confidence,source,status,created_at,updated_at) VALUES (42,'legacy_action','Legacy action',70,80,'legacy','open',?,?)",
            (now, now),
        )
        con.execute(
            "INSERT INTO integration_events(source,event_type,telegram_id,payload_json,status,created_at,attempt_count) VALUES ('relationship_manager','relationship_milestone',42,'{}','pending',?,0)",
            (now,),
        )
        con.commit()
    finally:
        con.close()


def run():
    with TemporaryDirectory() as td:
        root = Path(td)

        # Process-level duplicate protection.
        lock_path = root / "runtime" / "instance.lock"
        first_lock = SingleInstanceLock(lock_path).acquire()
        try:
            try:
                SingleInstanceLock(lock_path).acquire()
            except AlreadyRunningError:
                pass
            else:
                raise AssertionError("duplicate process lock should be rejected")
        finally:
            first_lock.release()

        # Migration + pre-v6 safety backup.
        legacy = root / "legacy_v5.db"
        legacy_v5_db(legacy)
        backup_dir = root / "pre_backups"
        settings = SimpleNamespace(database_path=legacy, backup_dir=backup_dir)
        safety = pre_upgrade_backup(settings, "6.0.0")
        assert safety and safety.name.startswith("pre_v6_") and safety.exists()
        db = Database(legacy)
        assert db.meta("schema_version") == "6.0.0"
        assert db.one("SELECT display_name FROM contacts WHERE telegram_id=42")["display_name"] == "Legacy Contact"
        action_cols = {r[1] for r in sqlite3.connect(legacy).execute("PRAGMA table_info(recommended_actions)").fetchall()}
        assert {"cooldown_until", "occurrence_count", "last_present_at"}.issubset(action_cols)
        event_cols = {r[1] for r in sqlite3.connect(legacy).execute("PRAGMA table_info(integration_events)").fetchall()}
        assert {"event_uuid", "event_version", "dedupe_key", "priority"}.issubset(event_cols)
        assert db.integrity_check() == ["ok"]

        # Fresh v6 policy lab.
        lab = Database(root / "lab.db")
        engine = RelationshipEngine(lab)
        engine.integration.export_dir = root / "integration"
        engine.integration.export_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)

        # Build contacts and action rows for workload-budget testing.
        for tid in range(100, 112):
            engine.upsert_identity(tid, f"u{tid}", f"Contact {tid}", now)
        lab.set_meta("daily_exception_limit", "5")
        lab.set_meta("exception_per_contact_limit", "1")
        lab.set_meta("exception_threshold", "50")
        lab.set_meta("exception_critical_threshold", "85")
        stamp = utcnow()
        # Two critical items + eight normal items.
        for tid, score in [(100, 95), (101, 90)] + [(x, 60) for x in range(102, 110)]:
            lab.execute(
                """INSERT INTO recommended_actions
                   (telegram_id,action_key,title,action_score,confidence,source,status,created_at,updated_at,occurrence_count,last_present_at)
                   VALUES (?,?,?,?,90,'release_test','open',?,?,1,?)""",
                (tid, f"k{tid}", f"Action {tid}", score, stamp, stamp, stamp),
            )
        selected = engine.exception_policy.select()
        assert len(selected) == 5
        assert {100, 101}.issubset({r["telegram_id"] for r in selected})
        policy = engine.exception_policy.summary()
        assert policy["eligible"] == 10 and policy["selected"] == 5 and policy["budget_suppressed"] == 5

        # Critical work bypasses the normal budget.
        for tid in range(110, 112):
            lab.execute(
                """INSERT INTO recommended_actions
                   (telegram_id,action_key,title,action_score,confidence,source,status,created_at,updated_at,occurrence_count,last_present_at)
                   VALUES (?,?,?,?,95,'release_test','open',?,?,1,?)""",
                (tid, f"critical{tid}", f"Critical {tid}", 99, stamp, stamp, stamp),
            )
        lab.set_meta("daily_exception_limit", "2")
        selected = engine.exception_policy.select()
        assert len(selected) >= 4  # 4 critical items survive a normal budget of 2.

        # Dismissal produces feedback + real cooldown.
        action_id = selected[0]["id"]
        assert engine.actions.resolve(action_id, "dismissed")
        cooled = lab.one("SELECT status,cooldown_until FROM recommended_actions WHERE id=?", (action_id,))
        assert cooled["status"] == "dismissed" and datetime.fromisoformat(cooled["cooldown_until"]) > datetime.now(timezone.utc)
        assert lab.one("SELECT outcome FROM action_feedback WHERE action_id=? ORDER BY id DESC LIMIT 1", (action_id,))["outcome"] == "dismissed"

        # Calibration cannot become less conservative than baseline.
        vendor_tid = 111
        for idx in range(5):
            lab.execute(
                "INSERT INTO classification_feedback(telegram_id,predicted_type,confidence,final_type,outcome,source,details,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (vendor_tid, "vendor", 90, "partner", "overridden", "admin", f"override {idx}", stamp),
            )
        engine.calibration.refresh()
        vendor = engine.calibration.policy_for("vendor")
        assert vendor["auto_enabled"] is False and vendor["threshold"] == 99
        customer = engine.calibration.policy_for("customer")
        assert customer["threshold"] >= int(lab.meta("classification_auto_threshold", "85"))

        # Integration contract is idempotent and exported with v6 metadata.
        e1 = engine.integration.emit("maintenance_warning", None, {"code": "release"})
        e2 = engine.integration.emit("maintenance_warning", None, {"code": "release"})
        assert e1 == e2
        _, exported = engine.integration.export_events(100)
        assert exported >= 1
        outbox = engine.integration.export_dir / "relationship_events_outbox.jsonl"
        events = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        event = next(x for x in events if x["event_type"] == "maintenance_warning")
        assert event["contract_version"] == "6.0" and event["event_uuid"] and event["priority"] >= 75

        # Healthy local SLO can reach PASS when all components are current.
        backups = BackupManager(lab, root / "backups")
        assert backups.create("release_test")["status"] == "verified"
        lab.set_meta("last_heartbeat", utcnow())
        lab.set_meta("last_intelligence_maintenance", utcnow())
        for component, status in (("telegram_monitor", "online"), ("scheduler", "ok"), ("admin_bot", "online")):
            lab.execute("INSERT INTO bot_health(component,status,details,created_at) VALUES (?,?,?,?)", (component, status, "release", utcnow()))
        ops = engine.operations.capture(run_integrity=True)
        assert ops["status"] == "pass" and ops["health_score"] >= 90

        # New query filters work without exposing suppressed work as active exceptions.
        rows = engine.query.search("quarantined")
        assert isinstance(rows, list)
        rows = engine.query.search("actionsuppressed")
        assert any(r["telegram_id"] == selected[0]["telegram_id"] for r in rows)

        report = engine.reporting.build("weekly")
        assert "policy_selected_exceptions" in report and "classifier_quarantined_types" in report
        assert report["operational_health"] is not None

        print("RELEASE TEST PASSED — VM Relationship Manager 6.0")
        print({
            "migration": "5.0.0 -> 6.0.0",
            "pre_v6_backup": "verified",
            "policy_selected": policy["selected"],
            "budget_suppressed": policy["budget_suppressed"],
            "vendor_calibration": "quarantined",
            "integration_contract": event["contract_version"],
            "ops_health": ops["health_score"],
            "schema": lab.meta("schema_version"),
        })


if __name__ == "__main__":
    run()
