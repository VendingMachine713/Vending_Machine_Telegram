from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .paths import project_root
from .adapters import _connect_readonly, _resolve_bot_path, _tables


def collect_relationship_presence(root: Path | None = None) -> dict[str, Any]:
    """Map dormant/cooling contacts to the chats where they are observed.

    This enables cross-bot reasoning against Universal Search chat activity while
    exposing only stable IDs and scores, never message text or private notes.
    """
    root = root or project_root()
    bot_dir = root / "bots" / "VM_Relationship_Manager"
    default = root / "shared" / "exports" / "VM_Relationship_Manager" / "vm_relationships.db"
    db_path = _resolve_bot_path(bot_dir, "DATABASE_PATH", default)
    con = _connect_readonly(db_path)
    if con is None:
        return {"available": False, "database": str(db_path), "reason": "database_unavailable"}

    shared = PlatformDB(root=root)
    shared.init()
    with shared.connect() as dst:
        dst.execute("UPDATE intelligence_signals SET status='INACTIVE',updated_at_utc=? WHERE signal_key LIKE 'relationship:presence:%'", (datetime.now(timezone.utc).isoformat(),))
    result = {"available": True, "database": str(db_path), "memberships": 0, "dormant_memberships": 0}
    try:
        tables = _tables(con)
        required = {"contacts", "contact_intelligence", "contact_groups"}
        if not required.issubset(tables):
            return {**result, "available": False, "reason": "required_tables_missing"}
        rows = con.execute("""
            SELECT c.telegram_id,c.relationship_type,c.activity_status,c.relationship_score,c.trust_score,
                   i.health_score,i.lifecycle_stage,i.days_overdue,
                   g.chat_id,g.interaction_count AS group_interactions,g.last_seen AS group_last_seen
            FROM contacts c
            JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
            JOIN contact_groups g ON g.telegram_id=c.telegram_id
            WHERE i.lifecycle_stage IN ('dormant','cooling') OR c.activity_status IN ('dormant','cooling')
        """).fetchall()
        result["memberships"] = len(rows)
        for row in rows:
            lifecycle = str(row["lifecycle_stage"] or row["activity_status"] or "unknown")
            contact_id = str(row["telegram_id"])
            chat_id = str(row["chat_id"])
            severity_score = max(20, min(100, 100 - int(row["health_score"] or 50)))
            shared.upsert_signal(
                f"relationship:presence:{contact_id}:{chat_id}",
                "relationship_dormant_presence" if lifecycle == "dormant" else "relationship_cooling_presence",
                f"A {lifecycle} relationship is present in this Telegram chat",
                subject_type="chat",
                subject_id=chat_id,
                score=severity_score,
                confidence=0.95,
                evidence={
                    "contact_id": contact_id,
                    "relationship_type": row["relationship_type"],
                    "lifecycle_stage": lifecycle,
                    "relationship_score": row["relationship_score"],
                    "trust_score": row["trust_score"],
                    "days_overdue": row["days_overdue"],
                    "group_interactions": row["group_interactions"],
                    "group_last_seen": row["group_last_seen"],
                },
            )
            if lifecycle == "dormant":
                result["dormant_memberships"] += 1
    finally:
        con.close()
    return result
