from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import json
from typing import Any

from .paths import project_root
from .manifests import discover_bots

EXCLUDED_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "env", "node_modules",
    "backups", "logs", "media_cache", "content", "downloads",
}

SENSITIVE_NAMES = {
    ".env", "secrets.json", "credentials.json", "config.env",
}

def _safe_tree(bot_dir: Path, max_depth: int = 3, max_files: int = 500) -> list[str]:
    lines: list[str] = []
    count = 0

    for path in sorted(bot_dir.rglob("*"), key=lambda p: str(p).lower()):
        try:
            rel = path.relative_to(bot_dir)
        except ValueError:
            continue

        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.name.lower() in SENSITIVE_NAMES:
            lines.append(f"{rel.as_posix()} [REDACTED FILE]")
            continue
        if len(rel.parts) > max_depth:
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
    bots = discover_bots(root)
    data = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "bots": [],
    }

    for bot in bots:
        bot_dir = Path(bot.path)
        data["bots"].append({
            "folder": bot.folder,
            "entrypoint": bot.entrypoint,
            "entrypoint_confidence": bot.entrypoint_confidence,
            "launchers": bot.launchers,
            "requirements": bot.requirements,
            "pyproject": bot.pyproject,
            "nested_duplicate_folder": bot.nested_duplicate_folder,
            "tree": _safe_tree(bot_dir),
        })
    return data


def write_structure_report(root: Path | None = None) -> tuple[Path, Path]:
    root = root or project_root()
    out = root / "diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    data = build_structure_report(root)

    json_path = out / "project_structure.json"
    txt_path = out / "project_structure.txt"

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "=" * 72,
        "VM PROJECT STRUCTURE",
        "=" * 72,
        f"Generated: {data['generated_at_utc']}",
        f"Root: {data['project_root']}",
        "",
    ]
    for bot in data["bots"]:
        lines += [
            f"[{bot['folder']}]",
            f"entrypoint={bot['entrypoint'] or 'not detected'}",
            f"entrypoint_confidence={bot['entrypoint_confidence']}",
            f"launchers={', '.join(bot['launchers']) if bot['launchers'] else 'none'}",
            f"nested_duplicate={bot['nested_duplicate_folder']}",
            "tree:",
        ]
        lines.extend("  " + line for line in bot["tree"])
        lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, txt_path
