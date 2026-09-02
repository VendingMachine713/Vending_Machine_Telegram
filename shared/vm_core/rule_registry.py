from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .calibration import calibration_report
from .db import PlatformDB, utcnow
from .paths import project_root


PROPOSAL_STATUSES = {"PROPOSED", "APPROVED", "REJECTED", "ACTIVATED", "ROLLED_BACK", "EXPIRED"}
ACTIVE_CALIBRATION_STATUSES = {"STRONG", "WEAK", "OVERCONFIDENT"}
MAX_SCORE_DELTA = 10.0


class RuleRegistryError(RuntimeError):
    """Raised when a governed rule-registry operation is invalid."""


@dataclass(frozen=True)
class RuleChangeDecision:
    proposal_id: int
    rule_id: str
    source_rule_version: int
    proposal_status: str
    actor: str
    event_id: int


def _ensure_schema(db: PlatformDB) -> None:
    with db.connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS intelligence_rule_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id TEXT NOT NULL,
                registry_version INTEGER NOT NULL,
                source_rule_version INTEGER NOT NULL,
                parent_registry_version INTEGER,
                score_delta REAL NOT NULL DEFAULT 0,
                rollout_percent INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                activated_at_utc TEXT,
                retired_at_utc TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(rule_id, registry_version)
            );

            CREATE TABLE IF NOT EXISTS intelligence_rule_change_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_key TEXT NOT NULL UNIQUE,
                rule_id TEXT NOT NULL,
                source_rule_version INTEGER NOT NULL,
                calibration_status TEXT NOT NULL,
                proposed_score_delta REAL NOT NULL,
                rationale TEXT NOT NULL,
                sample_size INTEGER NOT NULL,
                known_outcomes INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'PROPOSED',
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                decided_by TEXT,
                decision_note TEXT NOT NULL DEFAULT '',
                activated_registry_version INTEGER,
                rollout_percent INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_rule_versions_active
                ON intelligence_rule_versions(rule_id, status, registry_version);
            CREATE INDEX IF NOT EXISTS idx_rule_proposals_status
                ON intelligence_rule_change_proposals(status, updated_at_utc);
            CREATE INDEX IF NOT EXISTS idx_rule_proposals_rule
                ON intelligence_rule_change_proposals(rule_id, source_rule_version, status);
            """
        )


def sync_calibration_proposals(root: Path | None = None) -> dict[str, int]:
    """Persist actionable calibration proposals without applying them."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _ensure_schema(db)
    now = utcnow()
    created = 0
    refreshed = 0

    with db.connect() as con:
        for item in calibration_report(root):
            status = str(item.get("status") or "")
            delta = max(-MAX_SCORE_DELTA, min(MAX_SCORE_DELTA, float(item.get("proposed_score_delta") or 0)))
            if status not in ACTIVE_CALIBRATION_STATUSES or delta == 0:
                continue
            rule_id = str(item["rule_id"])
            source_rule_version = int(item["rule_version"])
            key = f"calibration:{rule_id}:v{source_rule_version}:{status}:{delta:+.2f}"
            existing = con.execute(
                "SELECT id,status FROM intelligence_rule_change_proposals WHERE proposal_key=?",
                (key,),
            ).fetchone()
            if existing is None:
                con.execute(
                    """
                    INSERT INTO intelligence_rule_change_proposals(
                        proposal_key,rule_id,source_rule_version,calibration_status,
                        proposed_score_delta,rationale,sample_size,known_outcomes,status,
                        created_at_utc,updated_at_utc,metadata_json
                    ) VALUES(?,?,?,?,?,?,?,?, 'PROPOSED',?,?,?)
                    """,
                    (
                        key, rule_id, source_rule_version, status, delta,
                        str(item.get("rationale") or "")[:2000], int(item.get("sample_size") or 0),
                        int(item.get("known_outcomes") or 0), now, now,
                        json.dumps({
                            "positive_rate": item.get("positive_rate"),
                            "weighted_value": item.get("weighted_value"),
                            "calibration_gap": item.get("calibration_gap"),
                            "automatic_application": False,
                        }, ensure_ascii=False),
                    ),
                )
                created += 1
            elif str(existing["status"]) == "PROPOSED":
                con.execute(
                    """
                    UPDATE intelligence_rule_change_proposals
                    SET rationale=?,sample_size=?,known_outcomes=?,updated_at_utc=?,metadata_json=?
                    WHERE id=?
                    """,
                    (
                        str(item.get("rationale") or "")[:2000], int(item.get("sample_size") or 0),
                        int(item.get("known_outcomes") or 0), now,
                        json.dumps({
                            "positive_rate": item.get("positive_rate"),
                            "weighted_value": item.get("weighted_value"),
                            "calibration_gap": item.get("calibration_gap"),
                            "automatic_application": False,
                        }, ensure_ascii=False),
                        int(existing["id"]),
                    ),
                )
                refreshed += 1
    return {"created": created, "refreshed": refreshed}


def proposals(root: Path | None = None, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _ensure_schema(db)
    query = "SELECT * FROM intelligence_rule_change_proposals"
    params: list[Any] = []
    if status:
        query += " WHERE status=?"
        params.append(status.upper())
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    with db.connect() as con:
        return [dict(row) for row in con.execute(query, params)]


def _proposal(db: PlatformDB, proposal_id: int) -> dict[str, Any]:
    with db.connect() as con:
        row = con.execute(
            "SELECT * FROM intelligence_rule_change_proposals WHERE id=?",
            (int(proposal_id),),
        ).fetchone()
    if row is None:
        raise RuleRegistryError(f"proposal not found: {proposal_id}")
    return dict(row)


def decide_proposal(
    proposal_id: int,
    decision: str,
    *,
    actor: str = "operator",
    note: str | None = None,
    root: Path | None = None,
) -> RuleChangeDecision:
    """Approve or reject one calibration proposal; approval does not activate it."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _ensure_schema(db)
    target = decision.upper().strip()
    if target not in {"APPROVED", "REJECTED"}:
        raise RuleRegistryError("decision must be APPROVED or REJECTED")
    actor = actor.strip() or "operator"
    now = utcnow()

    with db.connect() as con:
        row_obj = con.execute(
            "SELECT * FROM intelligence_rule_change_proposals WHERE id=?",
            (int(proposal_id),),
        ).fetchone()
        if row_obj is None:
            raise RuleRegistryError(f"proposal not found: {proposal_id}")
        row = dict(row_obj)
        if str(row["status"]) != "PROPOSED":
            raise RuleRegistryError(f"proposal is {row['status']}; only PROPOSED may be decided")
        con.execute(
            """
            UPDATE intelligence_rule_change_proposals
            SET status=?,decided_by=?,decision_note=?,updated_at_utc=? WHERE id=?
            """,
            (target, actor, (note or "")[:1000], now, int(proposal_id)),
        )
        payload = {
            "proposal_id": int(proposal_id), "rule_id": row["rule_id"],
            "source_rule_version": row["source_rule_version"], "status": target,
            "actor": actor, "note": (note or "")[:1000], "automatic_application": False,
        }
        cur = con.execute(
            """
            INSERT INTO events(event_type,source,payload_json,created_at_utc,event_version,severity,
                subject_type,subject_id,correlation_id,evidence_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"rule_change.{target.lower()}", "vm_core.rule_registry",
                json.dumps(payload, ensure_ascii=False), now, 1, "INFO", "rule", row["rule_id"],
                f"rule-change:{proposal_id}",
                json.dumps({"proposal_id": int(proposal_id)}, ensure_ascii=False),
            ),
        )
        event_id = int(cur.lastrowid)
    return RuleChangeDecision(int(proposal_id), str(row["rule_id"]), int(row["source_rule_version"]), target, actor, event_id)


def activate_proposal(
    proposal_id: int,
    *,
    actor: str = "operator",
    rollout_percent: int = 10,
    root: Path | None = None,
) -> RuleChangeDecision:
    """Activate an approved registry change with deterministic staged rollout.

    Activation only affects VM Brain recommendation priority calibration via
    `effective_score_delta`; it never executes Telegram actions or modifies bot-owned data.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _ensure_schema(db)
    actor = actor.strip() or "operator"
    rollout = max(1, min(100, int(rollout_percent)))
    now = utcnow()

    with db.connect() as con:
        row_obj = con.execute(
            "SELECT * FROM intelligence_rule_change_proposals WHERE id=?",
            (int(proposal_id),),
        ).fetchone()
        if row_obj is None:
            raise RuleRegistryError(f"proposal not found: {proposal_id}")
        row = dict(row_obj)
        if str(row["status"]) != "APPROVED":
            raise RuleRegistryError(f"proposal is {row['status']}; only APPROVED may be activated")
        existing_active = con.execute(
            "SELECT * FROM intelligence_rule_versions WHERE rule_id=? AND status='ACTIVE' ORDER BY registry_version DESC LIMIT 1",
            (row["rule_id"],),
        ).fetchone()
        parent = int(existing_active["registry_version"]) if existing_active else None
        next_version_row = con.execute(
            "SELECT COALESCE(MAX(registry_version),0)+1 FROM intelligence_rule_versions WHERE rule_id=?",
            (row["rule_id"],),
        ).fetchone()
        registry_version = int(next_version_row[0])
        if existing_active is not None:
            con.execute(
                "UPDATE intelligence_rule_versions SET status='RETIRED',retired_at_utc=? WHERE id=?",
                (now, int(existing_active["id"])),
            )
        con.execute(
            """
            INSERT INTO intelligence_rule_versions(
                rule_id,registry_version,source_rule_version,parent_registry_version,score_delta,
                rollout_percent,status,created_by,created_at_utc,activated_at_utc,metadata_json
            ) VALUES(?,?,?,?,?,?, 'ACTIVE',?,?,?,?)
            """,
            (
                row["rule_id"], registry_version, int(row["source_rule_version"]), parent,
                max(-MAX_SCORE_DELTA, min(MAX_SCORE_DELTA, float(row["proposed_score_delta"]))),
                rollout, actor, now, now,
                json.dumps({"proposal_id": int(proposal_id), "calibration_status": row["calibration_status"]}, ensure_ascii=False),
            ),
        )
        con.execute(
            """
            UPDATE intelligence_rule_change_proposals
            SET status='ACTIVATED',activated_registry_version=?,rollout_percent=?,updated_at_utc=? WHERE id=?
            """,
            (registry_version, rollout, now, int(proposal_id)),
        )
        cur = con.execute(
            """
            INSERT INTO events(event_type,source,payload_json,created_at_utc,event_version,severity,
                subject_type,subject_id,correlation_id,evidence_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "rule_change.activated", "vm_core.rule_registry",
                json.dumps({
                    "proposal_id": int(proposal_id), "rule_id": row["rule_id"],
                    "registry_version": registry_version, "rollout_percent": rollout,
                    "score_delta": float(row["proposed_score_delta"]), "actor": actor,
                    "automatic_execution": False,
                }, ensure_ascii=False),
                now, 1, "INFO", "rule", row["rule_id"], f"rule-change:{proposal_id}",
                json.dumps({"registry_version": registry_version, "proposal_id": int(proposal_id)}, ensure_ascii=False),
            ),
        )
        event_id = int(cur.lastrowid)
    return RuleChangeDecision(int(proposal_id), str(row["rule_id"]), int(row["source_rule_version"]), "ACTIVATED", actor, event_id)


def rollback_proposal(
    proposal_id: int,
    *,
    actor: str = "operator",
    note: str | None = None,
    root: Path | None = None,
) -> RuleChangeDecision:
    """Retire an activated calibration version and restore its parent when present."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _ensure_schema(db)
    actor = actor.strip() or "operator"
    now = utcnow()

    with db.connect() as con:
        row_obj = con.execute("SELECT * FROM intelligence_rule_change_proposals WHERE id=?", (int(proposal_id),)).fetchone()
        if row_obj is None:
            raise RuleRegistryError(f"proposal not found: {proposal_id}")
        row = dict(row_obj)
        if str(row["status"]) != "ACTIVATED" or row.get("activated_registry_version") is None:
            raise RuleRegistryError("only ACTIVATED proposals may be rolled back")
        version = con.execute(
            "SELECT * FROM intelligence_rule_versions WHERE rule_id=? AND registry_version=?",
            (row["rule_id"], int(row["activated_registry_version"])),
        ).fetchone()
        if version is None or str(version["status"]) != "ACTIVE":
            raise RuleRegistryError("activated registry version is no longer active")
        con.execute(
            "UPDATE intelligence_rule_versions SET status='ROLLED_BACK',retired_at_utc=? WHERE id=?",
            (now, int(version["id"])),
        )
        parent = version["parent_registry_version"]
        if parent is not None:
            con.execute(
                "UPDATE intelligence_rule_versions SET status='ACTIVE',retired_at_utc=NULL WHERE rule_id=? AND registry_version=?",
                (row["rule_id"], int(parent)),
            )
        con.execute(
            "UPDATE intelligence_rule_change_proposals SET status='ROLLED_BACK',updated_at_utc=?,decision_note=? WHERE id=?",
            (now, (note or "")[:1000], int(proposal_id)),
        )
        cur = con.execute(
            """
            INSERT INTO events(event_type,source,payload_json,created_at_utc,event_version,severity,
                subject_type,subject_id,correlation_id,evidence_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "rule_change.rolled_back", "vm_core.rule_registry",
                json.dumps({"proposal_id": int(proposal_id), "rule_id": row["rule_id"], "actor": actor,
                            "restored_registry_version": int(parent) if parent is not None else None,
                            "note": (note or "")[:1000]}, ensure_ascii=False),
                now, 1, "WARNING", "rule", row["rule_id"], f"rule-change:{proposal_id}",
                json.dumps({"rolled_back_registry_version": int(version["registry_version"])}, ensure_ascii=False),
            ),
        )
        event_id = int(cur.lastrowid)
    return RuleChangeDecision(int(proposal_id), str(row["rule_id"]), int(row["source_rule_version"]), "ROLLED_BACK", actor, event_id)


def active_rule_versions(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _ensure_schema(db)
    with db.connect() as con:
        return [dict(row) for row in con.execute(
            "SELECT * FROM intelligence_rule_versions WHERE status='ACTIVE' ORDER BY rule_id,registry_version DESC"
        )]


def effective_score_delta(rule_id: str, source_rule_version: int, subject_id: str | None, root: Path | None = None) -> float:
    """Return a governed staged score adjustment for one recommendation subject."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _ensure_schema(db)
    with db.connect() as con:
        row = con.execute(
            """
            SELECT * FROM intelligence_rule_versions
            WHERE rule_id=? AND source_rule_version=? AND status='ACTIVE'
            ORDER BY registry_version DESC LIMIT 1
            """,
            (rule_id, int(source_rule_version)),
        ).fetchone()
    if row is None:
        return 0.0
    rollout = max(0, min(100, int(row["rollout_percent"])))
    if rollout <= 0:
        return 0.0
    if rollout < 100:
        stable_subject = str(subject_id or "unknown")
        digest = sha256(f"{rule_id}:{stable_subject}".encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % 100
        if bucket >= rollout:
            return 0.0
    return max(-MAX_SCORE_DELTA, min(MAX_SCORE_DELTA, float(row["score_delta"])))


def registry_summary(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    sync = sync_calibration_proposals(root)
    rows = proposals(root, limit=500)
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
    return {
        "sync": sync,
        "proposal_counts": counts,
        "active_rule_versions": active_rule_versions(root),
        "automatic_approval": False,
        "automatic_activation": False,
        "automatic_execution": False,
    }
