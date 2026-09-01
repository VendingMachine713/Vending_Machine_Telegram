from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import shutil
import zipfile
from typing import Any
from .paths import project_root
from .duplicates import analyze_nested_duplicates

EXPECTED_DIFFERENT = {"CHANGELOG.md", "README.md", "START_VM_RELATIONSHIPS.ps1", "VERSION.txt"}
VERSION_RE = re.compile(r"(?im)^\s*Build:\s*(\d+(?:\.\d+)+)\s*$")


def _version(path: Path) -> tuple[int, ...] | None:
    if not path.is_file():
        return None
    match = VERSION_RE.search(path.read_text(encoding="utf-8", errors="ignore"))
    if not match:
        return None
    try:
        return tuple(int(x) for x in match.group(1).split("."))
    except ValueError:
        return None


def plan(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    data = analyze_nested_duplicates(root)
    item = next((b for b in data["bots"] if b["bot"] == "VM_Relationship_Manager"), None)
    if not item:
        return {"present": False, "safe_to_apply": False, "reason": "No nested Relationship Manager folder detected."}
    outer = root / "bots" / "VM_Relationship_Manager"
    nested = outer / "VM_Relationship_Manager"
    statuses = {r["relative_path"]: r["status"] for r in item["files"]}
    forbidden = []
    ignored_disposable = []
    for rel, state in statuses.items():
        low = rel.lower().replace("\\", "/")
        if state == "SENSITIVE_SKIPPED" and ("__pycache__/" in low or low.endswith(".pyc")):
            ignored_disposable.append(rel)
            continue
        if state in {"NESTED_ONLY", "SENSITIVE_SKIPPED", "ERROR"}:
            forbidden.append(rel)
    different = {p for p, state in statuses.items() if state == "DIFFERENT"}
    outer_v = _version(outer / "VERSION.txt")
    nested_v = _version(nested / "VERSION.txt")
    safe = (
        not forbidden
        and different.issubset(EXPECTED_DIFFERENT)
        and outer_v is not None
        and nested_v is not None
        and outer_v > nested_v
    )
    return {
        "present": True,
        "safe_to_apply": safe,
        "outer_version": ".".join(map(str, outer_v)) if outer_v else None,
        "nested_version": ".".join(map(str, nested_v)) if nested_v else None,
        "different_files": sorted(different),
        "exact_duplicate_files": sorted(p for p, state in statuses.items() if state == "EXACT_DUPLICATE"),
        "forbidden_or_unique_files": forbidden,
        "ignored_disposable_cache_files": sorted(ignored_disposable),
        "strategy": [
            "Preserve newer outer README, launcher and VERSION.",
            "Merge missing historical changelog sections from nested copy into outer changelog.",
            "Archive entire nested folder to ZIP.",
            "Remove nested folder only after archive verification.",
        ],
    }


def _merge_changelog(outer: Path, nested: Path) -> bool:
    if not nested.is_file():
        return False
    old = nested.read_text(encoding="utf-8", errors="replace")
    current = outer.read_text(encoding="utf-8", errors="replace") if outer.is_file() else "# VM Relationship Manager Changelog\n"
    sections = re.split(r"(?=^##\s+)", old, flags=re.M)
    additions = []
    for section in sections:
        match = re.match(r"^##\s+([^\r\n]+)", section)
        if not match:
            continue
        heading = match.group(1).strip()
        if heading.lower().startswith("update policy"):
            continue
        if ("## " + heading) not in current:
            additions.append(section.strip())
    if additions:
        outer.write_text(current.rstrip() + "\n\n" + "\n\n".join(additions) + "\n", encoding="utf-8")
        return True
    return False


def apply(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    cleanup_plan = plan(root)
    if not cleanup_plan.get("safe_to_apply"):
        return {"ok": False, "applied": False, "plan": cleanup_plan, "reason": "Safety gate rejected cleanup."}
    outer = root / "bots" / "VM_Relationship_Manager"
    nested = outer / "VM_Relationship_Manager"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = root / "backups" / f"relationship_nested_legacy_{stamp}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for fp in nested.rglob("*"):
            if fp.is_file():
                z.write(fp, (Path("VM_Relationship_Manager_nested") / fp.relative_to(nested)).as_posix())
    with zipfile.ZipFile(archive) as z:
        if not z.namelist():
            return {"ok": False, "applied": False, "reason": "Archive verification failed: archive is empty.", "plan": cleanup_plan}

    merged = _merge_changelog(outer / "CHANGELOG.md", nested / "CHANGELOG.md")
    shutil.rmtree(nested)
    return {
        "ok": True,
        "applied": True,
        "archive": str(archive),
        "changelog_history_merged": merged,
        "removed": str(nested),
        "plan": cleanup_plan,
    }


def write_plan(root: Path | None = None) -> Path:
    root = root or project_root()
    out = root / "diagnostics" / "relationship_cleanup_plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan(root), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
