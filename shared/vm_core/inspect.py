from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import json
from typing import Any
from .paths import project_root
from .manifests import discover_bots

EXCLUDED_DIRS = {".git","__pycache__", ".venv","venv","env","node_modules","backups","logs","media_cache","content","downloads"}
SENSITIVE_NAMES = {".env","secrets.json","credentials.json","config.env"}

def _safe_tree(bot_dir: Path, max_depth: int = 4, max_files: int = 1000) -> list[str]:
    lines, count = [], 0
    for path in sorted(bot_dir.rglob("*"), key=lambda p: str(p).lower()):
        rel = path.relative_to(bot_dir)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if len(rel.parts) > max_depth:
            continue
        if path.name.lower() in SENSITIVE_NAMES:
            lines.append(rel.as_posix() + " [REDACTED FILE]")
            continue
        if path.is_dir():
            lines.append(rel.as_posix() + "/")
        elif path.is_file():
            lines.append(rel.as_posix())
            count += 1
            if count >= max_files:
                lines.append("... file limit reached ...")
                break
    return lines

def build_structure_report(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    return {
        "schema_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "bots": [{
            "folder": b.folder,
            "classification": b.classification,
            "version": b.version,
            "entrypoint": b.entrypoint,
            "entrypoint_confidence": b.entrypoint_confidence,
            "launchers": b.launchers,
            "requirements": b.requirements,
            "pyproject": b.pyproject,
            "databases": b.databases,
            "tests": b.test_files,
            "nested_duplicate_folder": b.nested_duplicate_folder,
            "tree": _safe_tree(Path(b.path)),
        } for b in discover_bots(root)]
    }

def write_structure_report(root: Path | None = None) -> tuple[Path, Path]:
    root = root or project_root()
    out = root / "diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    data = build_structure_report(root)
    jp, tp = out / "project_structure.json", out / "project_structure.txt"
    jp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["="*72, "VM PROJECT STRUCTURE", "="*72, f"Generated: {data['generated_at_utc']}", f"Root: {data['project_root']}", ""]
    for b in data["bots"]:
        lines += [
            f"[{b['folder']}]",
            f"classification={b['classification']}",
            f"version={b['version'] or 'unknown'}",
            f"entrypoint={b['entrypoint'] or 'not detected'}",
            f"entrypoint_confidence={b['entrypoint_confidence']}",
            f"launchers={', '.join(b['launchers']) if b['launchers'] else 'none'}",
            f"nested_duplicate={b['nested_duplicate_folder']}",
            f"databases={len(b['databases'])}",
            f"tests={len(b['tests'])}",
            "tree:",
        ]
        lines.extend("  " + x for x in b["tree"])
        lines.append("")
    tp.write_text("\n".join(lines), encoding="utf-8")
    return jp, tp
