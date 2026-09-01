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
    "classification_engine", "action_engine", "autonomy_engine", "maintenance_engine",
    "calibration_engine", "exception_policy_engine", "operations_engine",
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
        print(f"[+] Monitoring phone: configured (ending {settings.phone[-4:]})" if settings.phone else "[+] Monitoring phone: not required while saved session remains authorised")
        print(f"[+] Session path: {settings.session_name}")
        session_file = Path(settings.session_name)
        if session_file.suffix != '.session':
            session_file = Path(str(session_file) + '.session')
        print(f"[+] Saved Telethon session: {'present' if session_file.exists() else 'missing'}")
        if not settings.phone and not session_file.exists():
            problems.append("No TELEGRAM_PHONE and saved Telethon session is missing; fresh authorisation would be impossible")
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
                autonomy = con.execute("SELECT meta_value FROM app_meta WHERE meta_key='autonomy_mode'").fetchone()
                autonomy = autonomy[0] if autonomy else "not-initialised"
                unknown = con.execute("SELECT COUNT(*) FROM contacts WHERE relationship_type='unknown'").fetchone()[0]
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                suggestions = con.execute("SELECT COUNT(*) FROM contact_classifications WHERE decision_state='suggested'").fetchone()[0] if 'contact_classifications' in tables else 0
                exceptions = con.execute("SELECT COUNT(*) FROM recommended_actions WHERE status IN ('open','snoozed') AND action_score>=50").fetchone()[0] if 'recommended_actions' in tables else 0
            finally:
                con.close()
            print(f"[+] Database schema: {schema}")
            print(f"[+] SQLite integrity: {integrity}")
            if schema != "6.0.0": problems.append(f"Schema is {schema}; expected 6.0.0")
            print(f"[+] Contacts preserved: {contacts}")
            if str(schema).startswith(('5.','6.')):
                print(f"[+] Autonomy mode: {autonomy}")
                if str(schema).startswith('6.'):
                    cal = con.execute("SELECT COUNT(*),SUM(CASE WHEN auto_enabled=0 THEN 1 ELSE 0 END) FROM classifier_calibration").fetchone() if 'classifier_calibration' in tables else (0,0)
                    ops = con.execute("SELECT health_score,status FROM operations_snapshots ORDER BY id DESC LIMIT 1").fetchone() if 'operations_snapshots' in tables else None
                    print(f"[+] Calibration types: {cal[0] or 0} | quarantined: {cal[1] or 0}")
                    if ops: print(f"[+] Operational health: {ops[0]}/100 ({ops[1]})")
                print(f"[+] Unknown contacts: {unknown} | classifier suggestions: {suggestions} | exception actions: {exceptions}")
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
