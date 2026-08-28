from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import re
from typing import Any

from .paths import project_root

VERSION_PATTERNS = (
    re.compile(r"\bv?(\d+\.\d+\.\d+(?:[-+._a-zA-Z0-9]*)?)\b"),
    re.compile(r"\bv?(\d+\.\d+(?:[-+._a-zA-Z0-9]*)?)\b"),
)

COMMON_ENTRY_NAMES = ("main.py", "app.py", "bot.py", "run.py", "__main__.py", "cli.py")
COMMON_CODE_DIRS = ("app", "src", "bot", "core", "service", "server")


@dataclass
class BotInfo:
    folder: str
    path: str
    manifest_present: bool
    version: str | None
    entrypoint: str | None
    entrypoint_confidence: str
    launchers: list[str]
    requirements: str | None
    pyproject: str | None
    databases: list[str]
    session_files: list[str]
    nested_duplicate_folder: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_version(bot_dir: Path) -> str | None:
    version_file = bot_dir / "VERSION"
    if version_file.is_file():
        value = version_file.read_text(encoding="utf-8", errors="ignore").strip()
        if value:
            return value[:80]

    manifest = bot_dir / "BOT_MANIFEST.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            value = data.get("version")
            if value:
                return str(value)
        except Exception:
            pass

    for name in ("README.md", "README.txt", "main.py", "app.py"):
        path = bot_dir / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:20000]
        except OSError:
            continue
        for pattern in VERSION_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1)
    return None


def _launcher_candidates(bot_dir: Path) -> list[str]:
    patterns = ("START*.bat", "START*.cmd", "START*.ps1", "RUN*.bat", "RUN*.cmd", "RUN*.ps1", "*.bat", "*.cmd")
    found: set[str] = set()
    for pattern in patterns:
        for p in bot_dir.glob(pattern):
            if p.is_file():
                found.add(p.name)
    return sorted(found)


def _entrypoint_from_launchers(bot_dir: Path, launchers: list[str]) -> tuple[str | None, str]:
    py_pattern = re.compile(r'(?i)(?:py(?:thon)?(?:\.exe)?\s+(?:-m\s+)?)(["\']?)([^"\']+?\.py)\1(?:\s|$)')
    module_pattern = re.compile(r'(?i)py(?:thon)?(?:\.exe)?\s+-m\s+([A-Za-z0-9_.]+)')
    for launcher in launchers:
        path = bot_dir / launcher
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = py_pattern.search(text)
        if m:
            rel = m.group(2).strip().replace("\\", "/")
            candidate = bot_dir / rel
            if candidate.is_file():
                return rel, "high"
        m = module_pattern.search(text)
        if m:
            mod = m.group(1)
            rel = Path(*mod.split("."))
            for candidate_rel in (rel.with_suffix(".py"), rel / "__main__.py"):
                candidate = bot_dir / candidate_rel
                if candidate.is_file():
                    return candidate_rel.as_posix(), "high"
    return None, "none"


def _entrypoint(bot_dir: Path, launchers: list[str]) -> tuple[str | None, str]:
    for name in COMMON_ENTRY_NAMES:
        if (bot_dir / name).is_file():
            return name, "high"

    from_launcher, confidence = _entrypoint_from_launchers(bot_dir, launchers)
    if from_launcher:
        return from_launcher, confidence

    for folder in COMMON_CODE_DIRS:
        sub = bot_dir / folder
        if not sub.is_dir():
            continue
        for name in COMMON_ENTRY_NAMES:
            candidate = sub / name
            if candidate.is_file():
                return candidate.relative_to(bot_dir).as_posix(), "medium"

    python_files = [
        p for p in bot_dir.glob("*.py")
        if not p.name.startswith(("test_", "smoke_", "setup", "migrate"))
    ]
    if len(python_files) == 1:
        return python_files[0].name, "low"

    return None, "none"


def inspect_bot(bot_dir: Path) -> BotInfo:
    launchers = _launcher_candidates(bot_dir)
    entrypoint, confidence = _entrypoint(bot_dir, launchers)

    dbs = sorted(
        str(p.relative_to(bot_dir))
        for pattern in ("*.db", "*.sqlite", "*.sqlite3")
        for p in bot_dir.rglob(pattern)
        if p.is_file()
    )[:100]
    sessions = sorted(
        str(p.relative_to(bot_dir))
        for p in bot_dir.rglob("*.session")
        if p.is_file()
    )[:100]

    return BotInfo(
        folder=bot_dir.name,
        path=str(bot_dir),
        manifest_present=(bot_dir / "BOT_MANIFEST.json").is_file(),
        version=_read_version(bot_dir),
        entrypoint=entrypoint,
        entrypoint_confidence=confidence,
        launchers=launchers,
        requirements="requirements.txt" if (bot_dir / "requirements.txt").is_file() else None,
        pyproject="pyproject.toml" if (bot_dir / "pyproject.toml").is_file() else None,
        databases=dbs,
        session_files=sessions,
        nested_duplicate_folder=(bot_dir / bot_dir.name).is_dir(),
    )


def discover_bots(root: Path | None = None) -> list[BotInfo]:
    root = root or project_root()
    bots_dir = root / "bots"
    if not bots_dir.is_dir():
        return []
    return [
        inspect_bot(path)
        for path in sorted(bots_dir.iterdir(), key=lambda p: p.name.lower())
        if path.is_dir() and not path.name.startswith((".", "__"))
    ]


def build_inventory(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    bots = discover_bots(root)
    return {
        "schema_version": 2,
        "project_root": str(root),
        "bot_count": len(bots),
        "bots": [bot.to_dict() for bot in bots],
    }


def write_inventory(root: Path | None = None) -> Path:
    root = root or project_root()
    output = root / "state" / "vm_inventory.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_inventory(root), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def _new_manifest(bot: BotInfo) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": bot.folder,
        "version": bot.version or "unknown",
        "status": "existing",
        "entrypoint": bot.entrypoint,
        "entrypoint_confidence": bot.entrypoint_confidence,
        "vm_core": {
            "compatible": True,
            "minimum_version": "0.2.0",
        },
        "discovery": {
            "launchers": bot.launchers,
            "requirements": bot.requirements,
            "pyproject": bot.pyproject,
        },
    }


def create_missing_bot_manifests(root: Path | None = None, *, write: bool = False) -> list[dict[str, Any]]:
    root = root or project_root()
    changes: list[dict[str, Any]] = []

    for bot in discover_bots(root):
        path = Path(bot.path) / "BOT_MANIFEST.json"
        if path.exists():
            changes.append({"bot": bot.folder, "action": "preserved", "path": str(path)})
            continue

        manifest = _new_manifest(bot)
        action = "would_create"
        if write:
            path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            action = "created"

        changes.append({
            "bot": bot.folder,
            "action": action,
            "path": str(path),
            "manifest": manifest,
        })

    return changes
