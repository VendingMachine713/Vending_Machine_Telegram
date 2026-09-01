from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import shutil
from typing import Any

from .paths import project_root

TARGETS = ("Universal_Search", "VM_Guard")
VM_WRAPPER_MARKERS = {
    "Universal_Search": ("shared.vm_core.search_index", "SearchIndex(ROOT)"),
    "VM_Guard": ("shared.vm_core.guard_engine", "guard_pass(ROOT)"),
}
DANGEROUS_LOG_RE = re.compile(
    r"""(?ix)
    \b(?:print|logger\.(?:debug|info|warning|error|critical)|logging\.(?:debug|info|warning|error|critical))
    \s*\(
    [^\n)]*
    (?:
        \b(?:BOT_TOKEN|API_HASH|API_ID|PASSWORD|SECRET|TOKEN|ACCESS_TOKEN|REFRESH_TOKEN)\b
        |
        \{[^}\n]*(?:BOT_TOKEN|API_HASH|API_ID|PASSWORD|SECRET|TOKEN|ACCESS_TOKEN|REFRESH_TOKEN)[^}\n]*\}
    )
    [^\n)]*
    \)
    """
)


SECRET_LITERAL_RE = re.compile(
    r"""(?x)
    \b\d{5,}:[A-Za-z0-9_-]{20,}\b
    |
    (?i:\b(?:api_hash|bot_token|access_token|refresh_token|password|secret)\b)
    \s*[:=]\s*
    ["'][^"'\n]{8,}["']
    """
)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _latest_pre_v13_snapshot(root: Path) -> Path | None:
    backups = root / "backups"
    if not backups.is_dir():
        return None
    candidates = [p for p in backups.glob("pre_v1_3_ecosystem_*") if p.is_dir()]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _looks_like_platform_wrapper(bot: str, text: str) -> bool:
    return any(marker in text for marker in VM_WRAPPER_MARKERS.get(bot, ()))


def _looks_unsafe_to_restore(text: str) -> list[str]:
    findings = []
    for n, line in enumerate(text.splitlines(), 1):
        if DANGEROUS_LOG_RE.search(line):
            findings.append(f"line {n}: possible credential logging")
        if SECRET_LITERAL_RE.search(line):
            findings.append(f"line {n}: possible hard-coded credential")
    return findings[:20]


def _merge_requirements(current: Path, legacy: Path, archive_copy: Path) -> dict[str, Any]:
    if not legacy.is_file():
        return {"changed": False, "reason": "legacy requirements missing"}
    legacy_text = legacy.read_text(encoding="utf-8-sig", errors="replace")
    archive_copy.write_text(legacy_text, encoding="utf-8")
    current_text = current.read_text(encoding="utf-8-sig", errors="replace") if current.is_file() else ""

    def normalized_lines(text: str) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(line)
        return out

    legacy_lines = normalized_lines(legacy_text)
    current_lines = normalized_lines(current_text)
    merged = list(legacy_lines)
    legacy_keys = {re.split(r"[<>=!~\[]", x, maxsplit=1)[0].strip().lower() for x in legacy_lines}
    for line in current_lines:
        key = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip().lower()
        if key not in legacy_keys:
            merged.append(line)
    new_text = (
        "# VM v1.4 merged requirements: legacy bot runtime + VM Core compatibility.\n"
        + "\n".join(merged)
        + ("\n" if merged else "")
    )
    changed = new_text != current_text
    if changed:
        current.write_text(new_text, encoding="utf-8")
    return {"changed": changed, "legacy_dependency_count": len(legacy_lines), "merged_dependency_count": len(merged)}


def recover(root: Path | None = None, *, apply: bool = False) -> dict[str, Any]:
    root = root or project_root()
    snapshot = _latest_pre_v13_snapshot(root)
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "apply": apply,
        "snapshot": str(snapshot) if snapshot else None,
        "bots": [],
    }
    if snapshot is None:
        report["ok"] = True
        report["reason"] = "No pre-v1.3 safety snapshot found; no legacy recovery attempted."
        return report

    all_ok = True
    for bot in TARGETS:
        src_dir = snapshot / "bots" / bot
        dst_dir = root / "bots" / bot
        src_main = src_dir / "main.py"
        item: dict[str, Any] = {"bot": bot, "source": str(src_main), "target": str(dst_dir / "legacy_main.py")}
        if not src_main.is_file():
            item.update({"eligible": False, "reason": "pre-v1.3 main.py missing"})
            report["bots"].append(item)
            continue

        text = src_main.read_text(encoding="utf-8-sig", errors="replace")
        if _looks_like_platform_wrapper(bot, text):
            item.update({"eligible": False, "reason": "snapshot main.py is already a VM Core wrapper"})
            report["bots"].append(item)
            continue
        unsafe = _looks_unsafe_to_restore(text)
        if unsafe:
            item.update({"eligible": False, "reason": "credential-logging safety scan failed", "findings": unsafe})
            all_ok = False
            report["bots"].append(item)
            continue

        item.update({"eligible": True, "source_sha256": _sha(src_main), "changed": False})
        target = dst_dir / "legacy_main.py"
        if target.is_file() and _sha(target) == _sha(src_main):
            item["legacy_main"] = "already recovered"
        elif apply:
            shutil.copy2(src_main, target)
            item["legacy_main"] = "recovered"
            item["changed"] = True
        else:
            item["legacy_main"] = "would recover"

        for name in ("README.md", "START.ps1", ".env.example"):
            src = src_dir / name
            if src.is_file():
                archive_name = f"LEGACY_{name.lstrip('.').replace('.', '_')}"
                dst = dst_dir / archive_name
                if apply and (not dst.exists() or _sha(dst) != _sha(src)):
                    shutil.copy2(src, dst)
                    item["changed"] = True
                item.setdefault("preserved_legacy_files", []).append(str(dst.relative_to(dst_dir)))

        legacy_req = src_dir / "requirements.txt"
        if legacy_req.is_file():
            req_result = {"changed": False, "reason": "preview"}
            if apply:
                req_result = _merge_requirements(
                    dst_dir / "requirements.txt",
                    legacy_req,
                    dst_dir / "LEGACY_requirements.txt",
                )
                item["changed"] = bool(item["changed"] or req_result.get("changed"))
            item["requirements"] = req_result

        item["legacy_components_present"] = {
            name: (dst_dir / name).is_file() for name in ("core.py", "envutil.py", ".env")
        }
        report["bots"].append(item)

    report["ok"] = all_ok
    return report


def write_report(root: Path | None = None, *, apply: bool = False) -> Path:
    root = root or project_root()
    report = recover(root, apply=apply)
    out = root / "diagnostics" / "legacy_recovery.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
