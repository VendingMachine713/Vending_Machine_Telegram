from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from config import load_settings

print("=" * 68)
print(" VM RELATIONSHIP MANAGER v6 - READ-ONLY LIVE STATE VERIFICATION")
print("=" * 68)

s = load_settings()
db_path = Path(s.database_path)

print(f"[+] Database path: {db_path}")
print(f"[+] Database exists: {db_path.exists()}")
print(f"[+] Session: {s.session_name}")
print(f"[+] Admin IDs configured: {len(s.admin_ids)}")
print("[+] Credential values are intentionally hidden.")

if not db_path.exists():
    print("[X] Live database file does not exist.")
    raise SystemExit(20)

con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

def scalar(sql, params=()):
    row = con.execute(sql, params).fetchone()
    return row[0] if row else None

def table_exists(name: str) -> bool:
    return bool(scalar(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ))

integrity = scalar("PRAGMA integrity_check")
print(f"[+] SQLite integrity: {integrity}")

schema = None
if table_exists("metadata"):
    try:
        schema = scalar("SELECT value FROM metadata WHERE key='schema_version'")
    except Exception:
        pass
if schema is None and table_exists("app_meta"):
    try:
        schema = scalar("SELECT value FROM app_meta WHERE key='schema_version'")
    except Exception:
        pass

print(f"[+] Schema marker: {schema or 'unknown'}")

counts = {}
for table in (
    "contacts",
    "relationship_events",
    "daily_activity",
    "attention_queue",
    "recommended_actions",
    "classification_feedback",
    "relationship_goals",
    "opportunities",
    "backup_audit",
):
    if table_exists(table):
        try:
            counts[table] = int(scalar(f'SELECT COUNT(*) FROM "{table}"') or 0)
        except Exception as exc:
            counts[table] = f"ERROR:{type(exc).__name__}"
    else:
        counts[table] = "missing"

print()
print("LIVE DATA COUNTS")
print("-" * 68)
for key, value in counts.items():
    print(f"{key:28} {value}")

# Contact state breakdown, if available.
if table_exists("contacts"):
    cols = {r["name"] for r in con.execute("PRAGMA table_info(contacts)").fetchall()}

    for column in ("relationship_type", "lifecycle_status", "status"):
        if column in cols:
            print()
            print(f"{column.upper()} BREAKDOWN")
            print("-" * 68)
            rows = con.execute(
                f'SELECT COALESCE(NULLIF(TRIM("{column}"),""), "(blank)") AS v, '
                f'COUNT(*) AS n FROM contacts GROUP BY v ORDER BY n DESC LIMIT 20'
            ).fetchall()
            for row in rows:
                print(f"{row['v'][:45]:48} {row['n']}")
            break

# Latest backups.
if table_exists("backup_audit"):
    cols = {r["name"] for r in con.execute("PRAGMA table_info(backup_audit)").fetchall()}
    if {"created_at", "status"}.issubset(cols):
        rows = con.execute(
            "SELECT created_at,status,path FROM backup_audit "
            "ORDER BY id DESC LIMIT 5"
        ).fetchall()
        print()
        print("LATEST BACKUP AUDIT")
        print("-" * 68)
        for row in rows:
            p = Path(row["path"]) if row["path"] else None
            print(
                f"{row['created_at']} | {row['status']} | "
                f"exists={bool(p and p.exists())}"
            )

con.close()

print()
contact_count = counts.get("contacts")
if isinstance(contact_count, int) and contact_count > 0:
    print(f"[+] CONTACT DATA PRESENT: {contact_count} contact(s).")
    print("[+] The earlier v6 bootstrap 'contacts=0' did NOT mean the CRM database was empty.")
elif contact_count == 0:
    print("[X] CONTACT TABLE IS EMPTY.")
    print("[!] Do not run destructive cleanup or initialise a replacement database.")
    print("[!] Existing shared backups should be inspected/restored before further writes.")
    raise SystemExit(30)
else:
    print("[X] Could not determine contact count safely.")
    raise SystemExit(31)

if str(integrity).lower() != "ok":
    print("[X] SQLite integrity check is not OK.")
    raise SystemExit(40)

print("[+] READ-ONLY V6 LIVE STATE VERIFICATION PASSED.")
