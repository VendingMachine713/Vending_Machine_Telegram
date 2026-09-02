
from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def fail(message: str) -> int:
    print(f"[X] PRE-FLIGHT FAILED: {message}")
    return 1


def main() -> int:
    try:
        ZoneInfo("Australia/Adelaide")
    except ZoneInfoNotFoundError:
        return fail(
            "Timezone data is unavailable. Install requirements with: "
            "py -m pip install -r requirements.txt"
        )

    try:
        from config import load_settings
        settings = load_settings()
    except Exception as exc:
        return fail(str(exc))

    if not settings.admin_ids:
        return fail("ADMIN_IDS is empty.")

    print("[+] PRE-FLIGHT PASSED")
    print(f"[+] Timezone: {settings.timezone.key}")
    print(f"[+] Admin IDs configured: {len(settings.admin_ids)}")
    print(f"[+] Database target: {settings.database_path}")
    print(f"[+] Backup target: {settings.backup_dir}")
    print(f"[+] Log target: {settings.log_dir}")
    print("[+] Telegram secrets detected without displaying them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
