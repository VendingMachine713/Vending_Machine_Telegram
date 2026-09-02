from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.security import central_owner_ids, write_central_owner_ids


def _read_int(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8", errors="ignore").strip())
        return value if value > 0 else None
    except Exception:
        return None


def _env_ids(path: Path, key: str) -> set[int]:
    if not path.is_file():
        return set()
    found: set[int] = set()
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, value = line.split("=", 1)
        if k.strip() != key:
            continue
        for item in re.split(r"[,;]", value.strip().strip('"').strip("'")):
            try:
                uid = int(item.strip())
            except ValueError:
                continue
            if uid > 0:
                found.add(uid)
    return found


def discover_existing_owner_ids() -> dict[str, set[int]]:
    sources: dict[str, set[int]] = {}
    for name, relative in {
        "VM_Guard": "bots/VM_Guard/state/admin_id.txt",
        "Universal_Search": "bots/Universal_Search/state/admin_id.txt",
        "VM_Ops_Control": "tools/vm_core/mobile_ops/state/admin_id.txt",
    }.items():
        uid = _read_int(ROOT / relative)
        if uid:
            sources[name] = {uid}

    admin_ids = _env_ids(ROOT / "bots/Admin_Command_Centre/.env", "VM_ADMIN_USER_IDS")
    if admin_ids:
        sources["Admin_Command_Centre"] = admin_ids

    return sources


def main() -> int:
    existing = central_owner_ids(ROOT)
    if existing:
        print(f"[OK] Central VM owner identity already configured for {len(existing)} user ID(s).")
        return 0

    sources = discover_existing_owner_ids()
    combined: set[int] = set().union(*sources.values()) if sources else set()

    if not combined:
        print("[ACTION REQUIRED] No existing local admin identity was found. No changes made.")
        print("Configure VM_OWNER_USER_IDS locally or create state/security/owner_user_ids.txt with your Telegram numeric user ID.")
        return 2

    if len(combined) != 1:
        print("[BLOCKED] Existing bot admin identities do not agree. No changes made.")
        for name, ids in sorted(sources.items()):
            print(f"  {name}: {len(ids)} configured ID(s)")
        print("Review the local identities before centralising ownership.")
        return 2

    owner_id = next(iter(combined))
    path = write_central_owner_ids([owner_id], ROOT)
    print("[OK] Central VM owner identity configured from agreeing existing bot ownership.")
    print(f"[LOCAL ONLY] {path}")
    print("Numeric ID value intentionally not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
