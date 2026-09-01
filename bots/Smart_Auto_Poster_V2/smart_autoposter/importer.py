from __future__ import annotations

import csv
from pathlib import Path
from .db import Database, utcnow

TRUE = {"1", "true", "yes", "y"}

def truth(v) -> int:
    return int(str(v or "").strip().lower() in TRUE)

def norm_mode(v: str) -> str:
    v = str(v or "review").strip().lower()
    return v if v in {"photo", "text", "disabled", "review"} else "review"

def import_config(db: Database, path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    added = updated = 0
    with path.open("r", newline="", encoding="utf-8-sig") as f, db.connect() as con:
        reader = csv.DictReader(f)
        required = {"group_id", "group_name", "primary_access", "secondary_access", "preferred_account", "recommended_mode", "needs_review"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError("Config CSV missing fields: " + ", ".join(sorted(missing)))
        for row in reader:
            try:
                gid = int(str(row["group_id"]).strip())
            except Exception:
                continue
            exists = con.execute("SELECT 1 FROM destinations WHERE group_id=?", (gid,)).fetchone()
            mode = norm_mode(row.get("recommended_mode"))
            review = truth(row.get("needs_review")) or mode == "review"
            enabled = int(mode in {"photo", "text"} and not review)
            values = (
                gid, str(row.get("group_name") or gid),
                truth(row.get("primary_access")), truth(row.get("secondary_access")),
                str(row.get("preferred_account") or "primary").strip().lower(), mode,
                enabled, int(review), str(row.get("notes") or ""), utcnow(),
            )
            con.execute('''
                INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,notes,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(group_id) DO UPDATE SET
                    group_name=excluded.group_name,
                    primary_access=excluded.primary_access,
                    secondary_access=excluded.secondary_access,
                    preferred_account=excluded.preferred_account,
                    mode=excluded.mode,
                    enabled=excluded.enabled,
                    needs_review=excluded.needs_review,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
            ''', values)
            if exists: updated += 1
            else: added += 1
    return {"added": added, "updated": updated}
