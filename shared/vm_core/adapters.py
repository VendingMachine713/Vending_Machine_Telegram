from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sqlite3
from typing import Any

from .db import PlatformDB
from .paths import project_root


def _env_value(path: Path, key: str) -> str | None:
    """Read one non-secret configuration value without loading the whole .env."""
    if not path.is_file():
        return None
    prefix = key + "="
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if line.startswith(prefix):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    except OSError:
        return None
    return None


def _resolve_bot_path(bot_dir: Path, env_key: str, default: Path) -> Path:
    raw = _env_value(bot_dir / ".env", env_key)
    if not raw:
        return default
    candidate = Path(os.path.expandvars(raw)).expanduser()
    if not candidate.is_absolute():
        candidate = bot_dir / candidate
    return candidate.resolve()


def _connect_readonly(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def _tables(con: sqlite3.Connection) -> set[str]:
    return {str(r[0]) for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def collect_autoposter_evidence(root: Path | None = None) -> dict[str, Any]:
    """Project current Smart Auto Poster operational evidence into VM Core.

    This is deliberately read-only against the bot-owned database. It creates
    shared incidents/signals only from explicit queue/account/campaign state and
    never changes queue rows or infers delivery from absence of evidence.
    """
    root = root or project_root()
    bot_dir = root / "bots" / "Smart_Auto_Poster_V2"
    db_path = _resolve_bot_path(bot_dir, "DATABASE_PATH", bot_dir / "data" / "smart_autoposter.sqlite3")
    con = _connect_readonly(db_path)
    if con is None:
        return {"available": False, "database": str(db_path), "reason": "database_unavailable"}

    shared = PlatformDB(root=root)
    shared.init()
    result: dict[str, Any] = {
        "available": True,
        "database": str(db_path),
        "campaigns": 0,
        "destinations": 0,
        "accounts": 0,
        "uncertain": 0,
        "failed_recent": 0,
        "sent_recent": 0,
    }
    try:
        tables = _tables(con)
        if "campaigns" in tables:
            rows = con.execute("SELECT campaign_id,enabled,lifecycle_state FROM campaigns").fetchall()
            result["campaigns"] = len(rows)
            for row in rows:
                state = str(row["lifecycle_state"] or "unknown")
                shared.upsert_signal(
                    f"autoposter:campaign:{row['campaign_id']}",
                    "campaign_state",
                    f"Campaign {row['campaign_id']} is {state}",
                    subject_type="campaign",
                    subject_id=str(row["campaign_id"]),
                    score=100 if int(row["enabled"] or 0) and state == "active" else 25,
                    confidence=1.0,
                    evidence={"enabled": bool(row["enabled"]), "lifecycle_state": state},
                    status="ACTIVE",
                )

        if "destinations" in tables:
            rows = con.execute("""
                SELECT group_id,group_name,enabled,needs_review,quarantine_until,
                       primary_access,secondary_access,last_post_at,next_eligible_at
                FROM destinations
            """).fetchall()
            result["destinations"] = len(rows)
            now = datetime.now(timezone.utc).isoformat()
            with shared.connect() as dst:
                for row in rows:
                    dst.execute("""
                        INSERT INTO destinations(
                            telegram_id,title,entity_type,active,primary_access,secondary_access,
                            source,last_seen_utc,metadata_json
                        ) VALUES(?,?, 'telegram_destination',?,?,?,?,?,?)
                        ON CONFLICT(telegram_id) DO UPDATE SET
                            title=excluded.title,active=excluded.active,
                            primary_access=excluded.primary_access,secondary_access=excluded.secondary_access,
                            source=excluded.source,last_seen_utc=excluded.last_seen_utc,
                            metadata_json=excluded.metadata_json
                    """, (
                        str(row["group_id"]), row["group_name"], int(bool(row["enabled"])),
                        row["primary_access"], row["secondary_access"], "Smart_Auto_Poster_V2", now,
                        __import__("json").dumps({
                            "needs_review": bool(row["needs_review"]),
                            "quarantine_until": row["quarantine_until"],
                            "last_post_at": row["last_post_at"],
                            "next_eligible_at": row["next_eligible_at"],
                        }, ensure_ascii=False),
                    ))

        if "accounts" in tables:
            rows = con.execute("""
                SELECT account_key,enabled,authorized,telegram_user_id,health_score,
                       cooldown_until,last_success_at,last_failure_at
                FROM accounts
            """).fetchall()
            result["accounts"] = len(rows)
            now = datetime.now(timezone.utc).isoformat()
            with shared.connect() as dst:
                for row in rows:
                    # Deliberately omit session paths and identities from shared intelligence.
                    dst.execute("""
                        INSERT INTO accounts(label,telegram_user_id,session_path,authorized,source,last_seen_utc,capabilities_json)
                        VALUES(?,?,?, ?,?,?,?)
                        ON CONFLICT(session_path) DO UPDATE SET
                            telegram_user_id=excluded.telegram_user_id,
                            authorized=excluded.authorized,source=excluded.source,
                            last_seen_utc=excluded.last_seen_utc,capabilities_json=excluded.capabilities_json
                    """, (
                        str(row["account_key"]), str(row["telegram_user_id"] or "") or None,
                        f"vm://account/{row['account_key']}", int(bool(row["authorized"])),
                        "Smart_Auto_Poster_V2", now,
                        __import__("json").dumps({
                            "enabled": bool(row["enabled"]),
                            "health_score": int(row["health_score"] or 0),
                            "cooldown_until": row["cooldown_until"],
                            "last_success_at": row["last_success_at"],
                            "last_failure_at": row["last_failure_at"],
                        }),
                    ))

        if "queue" in tables:
            uncertain = con.execute("""
                SELECT id,campaign_id,group_id,account_key,error_kind,updated_at
                FROM queue WHERE status='uncertain' ORDER BY id DESC
            """).fetchall()
            result["uncertain"] = len(uncertain)
            for row in uncertain:
                key = f"autoposter:uncertain:{row['id']}"
                shared.upsert_incident(
                    key, "campaign.delivery_uncertain", "Smart_Auto_Poster_V2", "ERROR",
                    f"Delivery for queue job #{row['id']} is UNCERTAIN; evidence-backed reconciliation required",
                    subject_type="destination", subject_id=str(row["group_id"]),
                    evidence={
                        "queue_id": row["id"], "campaign_id": row["campaign_id"],
                        "account_key": row["account_key"], "error_kind": row["error_kind"],
                        "updated_at": row["updated_at"], "automatic_retry": False,
                    },
                )
                shared.upsert_signal(
                    f"delivery-risk:{row['group_id']}", "delivery_risk",
                    "Smart Auto Poster has unresolved delivery evidence for this destination",
                    subject_type="destination", subject_id=str(row["group_id"]),
                    score=95, confidence=1.0,
                    evidence={"queue_id": row["id"], "campaign_id": row["campaign_id"], "status": "uncertain"},
                )

            cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
            failed = con.execute("""
                SELECT id,campaign_id,group_id,account_key,error_kind,last_error,updated_at
                FROM queue WHERE status IN ('failed','quarantined') AND updated_at>=? ORDER BY id DESC LIMIT 200
            """, (cutoff,)).fetchall()
            sent = con.execute("SELECT COUNT(*) FROM queue WHERE status='sent' AND updated_at>=?", (cutoff,)).fetchone()[0]
            result["failed_recent"] = len(failed)
            result["sent_recent"] = int(sent or 0)
            for row in failed:
                shared.upsert_signal(
                    f"delivery-failure:{row['id']}", "delivery_failure",
                    f"Recent posting failure: {row['error_kind'] or 'unknown'}",
                    subject_type="destination", subject_id=str(row["group_id"]),
                    score=70, confidence=1.0,
                    evidence={
                        "queue_id": row["id"], "campaign_id": row["campaign_id"],
                        "account_key": row["account_key"], "error_kind": row["error_kind"],
                        "updated_at": row["updated_at"],
                    },
                )
    finally:
        con.close()
    return result


def collect_relationship_evidence(root: Path | None = None) -> dict[str, Any]:
    """Project relationship lifecycle/momentum state into shared intelligence."""
    root = root or project_root()
    bot_dir = root / "bots" / "VM_Relationship_Manager"
    default = root / "shared" / "exports" / "VM_Relationship_Manager" / "vm_relationships.db"
    db_path = _resolve_bot_path(bot_dir, "DATABASE_PATH", default)
    con = _connect_readonly(db_path)
    if con is None:
        return {"available": False, "database": str(db_path), "reason": "database_unavailable"}

    shared = PlatformDB(root=root)
    shared.init()
    result = {"available": True, "database": str(db_path), "contacts": 0, "attention": 0, "dormant": 0, "growing": 0}
    try:
        tables = _tables(con)
        if not {"contacts", "contact_intelligence"}.issubset(tables):
            return {**result, "available": False, "reason": "required_tables_missing"}
        rows = con.execute("""
            SELECT c.telegram_id,c.relationship_type,c.activity_status,c.verification_status,
                   c.relationship_score,c.trust_score,c.last_seen,
                   i.health_score,i.momentum_label,i.momentum_score,i.lifecycle_stage,
                   i.days_overdue,i.suggested_action,i.computed_at
            FROM contacts c JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
        """).fetchall()
        result["contacts"] = len(rows)
        for row in rows:
            tid = str(row["telegram_id"])
            lifecycle = str(row["lifecycle_stage"] or row["activity_status"] or "unknown")
            momentum = str(row["momentum_label"] or "learning")
            if lifecycle == "dormant":
                result["dormant"] += 1
                shared.upsert_signal(
                    f"relationship:dormant:{tid}", "relationship_dormant",
                    "Relationship Manager classifies this contact as dormant",
                    subject_type="contact", subject_id=tid,
                    score=max(0, 100 - int(row["health_score"] or 0)), confidence=0.95,
                    evidence={
                        "relationship_type": row["relationship_type"],
                        "activity_status": row["activity_status"],
                        "health_score": row["health_score"], "days_overdue": row["days_overdue"],
                        "computed_at": row["computed_at"],
                    },
                )
            if momentum in {"growing", "surging"}:
                result["growing"] += 1
                shared.upsert_signal(
                    f"relationship:momentum:{tid}", "relationship_momentum",
                    f"Relationship momentum is {momentum}",
                    subject_type="contact", subject_id=tid,
                    score=min(100, max(0, 50 + int(row["momentum_score"] or 0) / 2)), confidence=0.9,
                    evidence={"momentum": momentum, "momentum_score": row["momentum_score"], "computed_at": row["computed_at"]},
                )

        if "attention_queue" in tables:
            attention = con.execute("""
                SELECT id,telegram_id,priority,category,title,created_at
                FROM attention_queue WHERE status='open' ORDER BY id DESC LIMIT 200
            """).fetchall()
            result["attention"] = len(attention)
            for row in attention:
                shared.upsert_signal(
                    f"relationship:attention:{row['id']}", "relationship_attention",
                    str(row["title"]), subject_type="contact",
                    subject_id=str(row["telegram_id"] or "unknown"),
                    score={"critical": 95, "high": 80, "medium": 60, "low": 40}.get(str(row["priority"]).lower(), 50),
                    confidence=1.0,
                    evidence={"attention_id": row["id"], "category": row["category"], "priority": row["priority"], "created_at": row["created_at"]},
                )
    finally:
        con.close()
    return result


def collect_all_bot_evidence(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    return {
        "Smart_Auto_Poster_V2": collect_autoposter_evidence(root),
        "VM_Relationship_Manager": collect_relationship_evidence(root),
    }
