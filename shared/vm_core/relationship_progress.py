from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _resolve_bot_path, _tables
from .paths import project_root
from .progress import ProgressLine, progress_snapshot


def relationship_manager_progress(root: Path | None = None) -> dict[str, Any]:
    """Return read-only Relationship Manager intelligence/attention progress."""
    root = root or project_root()
    bot_dir = root / "bots" / "VM_Relationship_Manager"
    default = root / "shared" / "exports" / "VM_Relationship_Manager" / "vm_relationships.db"
    db_path = _resolve_bot_path(bot_dir, "DATABASE_PATH", default)
    con = _connect_readonly(db_path)
    if con is None:
        return progress_snapshot(
            headline="VM RELATIONSHIP MANAGER",
            overall=ProgressLine("Relationship database unavailable", status="DEGRADED", detail=str(db_path)),
            recovery_messages=["Relationship intelligence state is unavailable; no contact state was inferred."],
        )

    try:
        tables = _tables(con)
        if not {"contacts", "contact_intelligence"}.issubset(tables):
            return progress_snapshot(
                headline="VM RELATIONSHIP MANAGER - UNIVERSAL PROGRESS",
                overall=ProgressLine("Relationship intelligence unavailable", status="DEGRADED"),
                recovery_messages=["Required contacts/contact_intelligence tables are missing."],
            )

        contacts = int(con.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] or 0)
        intelligent = int(
            con.execute(
                "SELECT COUNT(DISTINCT c.telegram_id) FROM contacts c JOIN contact_intelligence i ON i.telegram_id=c.telegram_id"
            ).fetchone()[0]
            or 0
        )
        dormant = int(
            con.execute(
                """
                SELECT COUNT(*) FROM contacts c JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
                WHERE lower(COALESCE(i.lifecycle_stage,c.activity_status,''))='dormant'
                """
            ).fetchone()[0]
            or 0
        )
        growing = int(
            con.execute(
                "SELECT COUNT(*) FROM contact_intelligence WHERE lower(COALESCE(momentum_label,'')) IN ('growing','surging')"
            ).fetchone()[0]
            or 0
        )
        overdue = int(
            con.execute("SELECT COUNT(*) FROM contact_intelligence WHERE COALESCE(days_overdue,0)>0").fetchone()[0]
            or 0
        )
        low_health = int(
            con.execute("SELECT COUNT(*) FROM contact_intelligence WHERE COALESCE(health_score,100)<40").fetchone()[0]
            or 0
        )

        attention = con.execute(
            """
            SELECT c.telegram_id,c.relationship_type,c.activity_status,
                   i.health_score,i.momentum_label,i.lifecycle_stage,i.days_overdue,
                   i.suggested_action,i.computed_at
            FROM contacts c JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
            ORDER BY COALESCE(i.days_overdue,0) DESC,COALESCE(i.health_score,100) ASC,c.telegram_id
            LIMIT 1
            """
        ).fetchone()

        recovery: list[str] = []
        if overdue:
            recovery.append(f"{overdue} relationship(s) are overdue for attention; review suggested actions rather than sending automatically.")
        if dormant:
            recovery.append(f"{dormant} relationship(s) are classified dormant and may need manual follow-up prioritisation.")
        if low_health:
            recovery.append(f"{low_health} relationship(s) have health scores below 40 and should be reviewed.")

        status = "ATTENTION" if overdue or dormant or low_health else ("READY" if contacts else "IDLE")
        overall = ProgressLine(
            "Relationship intelligence coverage",
            current=intelligent,
            total=contacts,
            status=status,
            detail=f"contacts={contacts} intelligence={intelligent} overdue={overdue} dormant={dormant}",
        )

        group = None
        task = None
        if attention:
            tid = str(attention["telegram_id"])
            days = int(attention["days_overdue"] or 0)
            health = int(attention["health_score"] or 0)
            group = ProgressLine(
                f"Contact {tid}",
                current=0 if days > 0 or health < 40 else 1,
                total=1,
                status="ATTENTION" if days > 0 or health < 40 else "HEALTHY",
                detail=(
                    f"type={attention['relationship_type'] or 'unknown'} lifecycle={attention['lifecycle_stage'] or attention['activity_status'] or 'unknown'} "
                    f"health={health} momentum={attention['momentum_label'] or 'unknown'} overdue={days}d"
                ),
            )
            task = ProgressLine(
                "Suggested relationship action",
                current=0 if attention["suggested_action"] else 1,
                total=1,
                status="REVIEW" if attention["suggested_action"] else "CLEAR",
                detail=str(attention["suggested_action"] or "No suggested action"),
            )

        return progress_snapshot(
            headline="VM RELATIONSHIP MANAGER - UNIVERSAL PROGRESS",
            overall=overall,
            group=group,
            task=task,
            metrics={
                "contacts": contacts,
                "intelligence_coverage": f"{intelligent}/{contacts}",
                "overdue": overdue,
                "dormant": dormant,
                "growing_or_surging": growing,
                "low_health": low_health,
            },
            recovery_messages=recovery,
        )
    finally:
        con.close()
