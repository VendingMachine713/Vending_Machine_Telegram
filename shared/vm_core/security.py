from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from .paths import project_root

OWNER_ENV = "VM_OWNER_USER_IDS"
SECURITY_STATE_DIR = Path("state") / "security"
OWNER_FILE_NAME = "owner_user_ids.txt"


@dataclass(frozen=True)
class SecurityFinding:
    service: str
    status: str
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def parse_user_ids(value: str | None) -> tuple[int, ...]:
    ids: set[int] = set()
    for raw in (value or "").replace(";", ",").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            uid = int(raw)
        except ValueError:
            continue
        if uid > 0:
            ids.add(uid)
    return tuple(sorted(ids))


def central_owner_file(root: Path | None = None) -> Path:
    root = root or project_root()
    return root / SECURITY_STATE_DIR / OWNER_FILE_NAME


def central_owner_ids(root: Path | None = None) -> tuple[int, ...]:
    """Return the platform owner allowlist.

    Environment configuration is authoritative when present. Otherwise the
    local state file is used. Nothing is auto-claimed: an empty result means
    control code must fail closed.
    """
    env_value = os.getenv(OWNER_ENV, "").strip()
    if env_value:
        return parse_user_ids(env_value)
    path = central_owner_file(root)
    if not path.is_file():
        return ()
    return parse_user_ids(path.read_text(encoding="utf-8", errors="ignore"))


def owner_authorized(user_id: int | None, root: Path | None = None) -> bool:
    if not user_id:
        return False
    return int(user_id) in set(central_owner_ids(root))


def write_central_owner_ids(ids: Iterable[int], root: Path | None = None) -> Path:
    """Write owner IDs to local-only platform state.

    Callers should use this only from a trusted local setup/migration path.
    """
    root = root or project_root()
    clean = tuple(sorted({int(v) for v in ids if int(v) > 0}))
    if not clean:
        raise ValueError("At least one positive Telegram numeric user ID is required.")
    path = central_owner_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(",".join(str(v) for v in clean) + "\n", encoding="utf-8")
    return path


def _source_text(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _has_all(text: str, needles: Iterable[str]) -> bool:
    return all(n in text for n in needles)


def _bot_findings(root: Path) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []

    guard = _source_text(root, "bots/VM_Guard/main.py")
    if guard:
        ok = _has_all(guard, ('effective_chat.type=="private"', 'ADMIN_FILE=STATE/"admin_id.txt"', 'CommandHandler("claim",claim)'))
        findings.append(SecurityFinding("VM_Guard", "PASS" if ok else "FAIL", "PRIVATE_OWNER_CONTROL", "Private-chat owner gate and private claim path detected." if ok else "Expected private owner/claim controls were not detected."))

    search = _source_text(root, "bots/Universal_Search/main.py")
    if search:
        ok = _has_all(search, ('effective_chat.type == "private"', 'CallbackQueryHandler(search_page_callback', 'CommandHandler("claim", claim)'))
        findings.append(SecurityFinding("Universal_Search", "PASS" if ok else "FAIL", "PRIVATE_OWNER_CONTROL", "Private owner gate covers commands/callback surface." if ok else "Expected private owner/callback controls were not detected."))

    relationship = _source_text(root, "bots/VM_Relationship_Manager/admin_bot.py")
    if relationship:
        cmd_ok = "user.id not in self.settings.admin_ids" in relationship
        cb_ok = "async def callback" in relationship and "if not await self.allowed(update)" in relationship
        ok = cmd_ok and cb_ok
        findings.append(SecurityFinding("VM_Relationship_Manager", "PASS" if ok else "FAIL", "ADMIN_ALLOWLIST", "Commands and callbacks are admin-ID gated." if ok else "Admin allowlist coverage is incomplete."))

    admin_core = _source_text(root, "bots/Admin_Command_Centre/admin_core.py")
    admin_main = _source_text(root, "bots/Admin_Command_Centre/main.py")
    if admin_core or admin_main:
        id_ok = "VM_ADMIN_USER_IDS" in admin_core and "if not is_admin(user_id,cfg)" in admin_core
        claim_ok = "get('chat') or {}).get('type')=='private'" in admin_main
        ok = id_ok and claim_ok
        findings.append(SecurityFinding("Admin_Command_Centre", "PASS" if ok else "FAIL", "ADMIN_ALLOWLIST", "Numeric admin IDs and private-only claim detected." if ok else "Admin allowlist/private claim coverage is incomplete."))

    ops = _source_text(root, "tools/vm_core/mobile_ops/ops_bot.py")
    if ops:
        ok = "update.effective_chat.type==\"private\"" in ops and "admin_id()==update.effective_user.id" in ops
        findings.append(SecurityFinding("VM_Ops_Control", "PASS" if ok else "FAIL", "PRIVATE_OWNER_CONTROL", "Private registered-admin control detected." if ok else "Private admin gate was not detected."))

    sap = _source_text(root, "bots/Smart_Auto_Poster_V2/smart_autoposter/admin_bot.py")
    if sap:
        auth_ok = "if not self.authorized(sender):" in sap
        mutation_ok = "and not self.can_control(sender)" in sap
        findings.append(SecurityFinding("Smart_Auto_Poster_V2", "PASS" if auth_ok and mutation_ok else "FAIL", "ROLE_ALLOWLIST", "Numeric allowlist and mutation-role checks detected." if auth_ok and mutation_ok else "Admin/callback role coverage is incomplete."))

    return findings


def group_safe_preflight(root: Path | None = None) -> dict:
    root = root or project_root()
    findings = _bot_findings(root)
    owners = central_owner_ids(root)

    owner_status = "PASS" if owners else "WARN"
    owner_detail = (
        f"Central owner identity configured for {len(owners)} Telegram user ID(s)."
        if owners
        else f"{OWNER_ENV} / {central_owner_file(root)} is not configured yet; existing per-bot local owner IDs remain authoritative."
    )
    findings.insert(0, SecurityFinding("VM_Core", owner_status, "CENTRAL_OWNER_IDENTITY", owner_detail))

    failures = sum(1 for f in findings if f.status == "FAIL")
    warnings = sum(1 for f in findings if f.status == "WARN")
    return {
        "group_safe": failures == 0,
        "failures": failures,
        "warnings": warnings,
        "owner_ids_configured": len(owners),
        "findings": [f.as_dict() for f in findings],
    }


def format_group_safe_report(report: dict) -> str:
    lines = [
        "VM GROUP DEPLOYMENT SECURITY",
        "=" * 32,
        f"GROUP_SAFE: {'YES' if report['group_safe'] else 'NO'}",
        f"Failures: {report['failures']} | Warnings: {report['warnings']}",
        "",
    ]
    for row in report["findings"]:
        lines.append(f"{row['status']:<5} {row['service']:<26} {row['code']}")
        lines.append(f"      {row['detail']}")
    return "\n".join(lines)
