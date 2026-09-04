"""Canonical aggregate evidence for the completed product workflows.

Only bounded counts/statuses cross the bot boundary. Raw Telegram IDs,
message text, usernames, notes, and business values remain in bot-owned DBs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _resolve_bot_path, _tables
from .db import PlatformDB
from .paths import project_root


def _inactive(db: PlatformDB, prefix: str) -> None:
    from datetime import datetime, timezone
    with db.connect() as con:
        con.execute("UPDATE intelligence_signals SET status='INACTIVE',updated_at_utc=? WHERE signal_key LIKE ?", (datetime.now(timezone.utc).isoformat(), prefix + "%"))


def collect_product_workflow_evidence(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    db = PlatformDB(root=root); db.init()
    result: dict[str, Any] = {"universal_search": {"available": False}, "relationship_manager": {"available": False}}

    search_dir = root / "bots" / "Universal_Search"
    search_path = _resolve_bot_path(search_dir, "DATABASE_PATH", search_dir / "data" / "universal_search.db")
    con = _connect_readonly(search_path)
    if con is not None:
        try:
            tables = _tables(con)
            if "marketplace_listings" in tables:
                counts = {f"{r['kind']}:{r['status']}": int(r["n"]) for r in con.execute("SELECT kind,status,COUNT(*) AS n FROM marketplace_listings GROUP BY kind,status")}
                matches = int(con.execute("SELECT COUNT(*) FROM marketplace_matches WHERE status='new'").fetchone()[0]) if "marketplace_matches" in tables else 0
                feedback = {str(r["outcome"]): int(r["n"]) for r in con.execute("SELECT outcome,COUNT(*) AS n FROM marketplace_match_feedback GROUP BY outcome")} if "marketplace_match_feedback" in tables else {}
                _inactive(db, "workflow:universal_search:")
                db.upsert_signal("workflow:universal_search:marketplace", "workflow_marketplace_health", "Universal Search marketplace workflow aggregate evidence", subject_type="service", subject_id="Universal_Search", score=min(100, 50 + matches * 5), confidence=0.95, evidence={"listing_counts": counts, "new_match_count": matches, "feedback_counts": feedback})
                result["universal_search"] = {"available": True, "listing_counts": counts, "new_match_count": matches, "feedback_counts": feedback}
        finally:
            con.close()

    rm_dir = root / "bots" / "VM_Relationship_Manager"
    rm_path = _resolve_bot_path(rm_dir, "DATABASE_PATH", root / "shared" / "exports" / "VM_Relationship_Manager" / "vm_relationships.db")
    con = _connect_readonly(rm_path)
    if con is not None:
        try:
            tables = _tables(con)
            if "business_import_runs" in tables:
                row = con.execute("SELECT COUNT(*) AS runs,COALESCE(SUM(duplicate_rows),0) AS duplicates,COALESCE(SUM(problem_rows),0) AS problems,COALESCE(SUM(valid_rows),0) AS valid FROM business_import_runs").fetchone()
                corrections = int(con.execute("SELECT COUNT(*) FROM admin_audit WHERE action='business_transaction_corrected'").fetchone()[0]) if "admin_audit" in tables else 0
                _inactive(db, "workflow:relationship_manager:")
                db.upsert_signal("workflow:relationship_manager:data_quality", "workflow_business_memory_quality", "Relationship Manager import and correction aggregate evidence", subject_type="service", subject_id="VM_Relationship_Manager", score=min(100, 50 + corrections * 2), confidence=0.95, evidence={"import_runs": int(row["runs"]), "valid_rows": int(row["valid"]), "duplicate_rows": int(row["duplicates"]), "problem_rows": int(row["problems"]), "correction_count": corrections})
                result["relationship_manager"] = {"available": True, "import_runs": int(row["runs"]), "valid_rows": int(row["valid"]), "duplicate_rows": int(row["duplicates"]), "problem_rows": int(row["problems"]), "correction_count": corrections}
        finally:
            con.close()
    return result
