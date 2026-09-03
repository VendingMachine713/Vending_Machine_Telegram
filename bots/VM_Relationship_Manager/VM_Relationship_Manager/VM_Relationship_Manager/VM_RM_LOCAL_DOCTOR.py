from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

from config import load_settings

REQUIRED_MODULES = [
    "database", "relationship_engine", "behavior_engine", "network_engine",
    "opportunity_engine", "priority_engine", "memory_engine", "group_engine",
    "risk_engine", "reporting_engine", "goal_engine", "segment_engine",
    "session_engine", "forecast_engine", "data_quality_engine", "playbook_engine",
    "briefing_engine", "integration_engine", "privacy_engine", "automation_engine",
]


def main() -> int:
    print("=" * 66)
    print(" VM RELATIONSHIP MANAGER - LOCAL DOCTOR")
    print("=" * 66)
    problems = []

    for name in REQUIRED_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            problems.append(f"Import {name}: {type(exc).__name__}: {exc}")
    print(f"[{'+' if not problems else '!'}] Module imports: {len(REQUIRED_MODULES)-len(problems)}/{len(REQUIRED_MODULES)} OK")

    try:
        settings = load_settings()
        print(f"[+] Timezone: {settings.timezone.key if hasattr(settings.timezone, 'key') else settings.timezone}")
        print(f"[+] Admin IDs configured: {len(settings.admin_ids)}")
        print(f"[+] Monitoring phone ending: {settings.phone[-4:]}")
        print(f"[+] Session path: {settings.session_name}")
        db_path = settings.database_path
    except Exception as exc:
        problems.append(f"Configuration: {type(exc).__name__}: {exc}")
        db_path = None

    if db_path and db_path.exists():
        try:
            con = sqlite3.connect(db_path)
            try:
                integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
                row = con.execute("SELECT meta_value FROM app_meta WHERE meta_key='schema_version'").fetchone()
                schema = row[0] if row else "legacy"
                contacts = con.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
            finally:
                con.close()
            print(f"[+] Database schema: {schema}")
            print(f"[+] SQLite integrity: {integrity}")
            print(f"[+] Contacts preserved: {contacts}")
            if integrity != "ok": problems.append(f"SQLite integrity: {integrity}")
        except Exception as exc:
            problems.append(f"Database: {type(exc).__name__}: {exc}")
    elif db_path:
        print("[!] Live database does not exist yet; it will be created at first startup.")

    if problems:
        print("\n[!] DOCTOR RESULT: WARN/FAIL")
        for p in problems:
            print(" -", p)
        return 1
    print("\n[+] DOCTOR RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
