from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import re
from typing import Any
from .paths import project_root
from .db import PlatformDB

COMMON_ENTRY_NAMES = ("main.py", "app.py", "bot.py", "run.py", "__main__.py", "cli.py")
COMMON_CODE_DIRS = ("app", "src", "bot", "core", "service", "server")
SOURCE_SUFFIXES = {".py", ".pyw", ".js", ".ts", ".go", ".rs"}
VERSION_PATTERNS = (
    re.compile(r"\bv?(\d+\.\d+\.\d+(?:[-+._a-zA-Z0-9]*)?)\b"),
    re.compile(r"\bv?(\d+\.\d+(?:[-+._a-zA-Z0-9]*)?)\b"),
)

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
    test_files: list[str]
    nested_duplicate_folder: bool
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def _launcher_candidates(bot_dir: Path) -> list[str]:
    found = set()
    for pattern in ("START*.bat", "START*.cmd", "START*.ps1", "RUN*.bat", "RUN*.cmd", "RUN*.ps1", "*.bat", "*.cmd"):
        for p in bot_dir.glob(pattern):
            if p.is_file():
                found.add(p.name)
    return sorted(found)

def _entrypoint_from_launchers(bot_dir: Path, launchers: list[str]) -> tuple[str | None, str]:
    py_pattern = re.compile(r'(?i)(?:py(?:thon)?(?:\.exe)?\s+)(?:-m\s+)?["\']?([^"\']+?\.py)["\']?(?:\s|$)')
    module_pattern = re.compile(r'(?i)py(?:thon)?(?:\.exe)?\s+-m\s+([A-Za-z0-9_.]+)')
    for launcher in launchers:
        try:
            text = (bot_dir / launcher).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = py_pattern.search(text)
        if m:
            rel = m.group(1).strip().replace("\\", "/")
            if (bot_dir / rel).is_file():
                return rel, "high"
        m = module_pattern.search(text)
        if m:
            rel = Path(*m.group(1).split("."))
            for c in (rel.with_suffix(".py"), rel / "__main__.py"):
                if (bot_dir / c).is_file():
                    return c.as_posix(), "high"
    return None, "none"

def _entrypoint(bot_dir: Path, launchers: list[str]) -> tuple[str | None, str]:
    for name in COMMON_ENTRY_NAMES:
        if (bot_dir / name).is_file():
            return name, "high"
    result = _entrypoint_from_launchers(bot_dir, launchers)
    if result[0]:
        return result
    for folder in COMMON_CODE_DIRS:
        sub = bot_dir / folder
        if not sub.is_dir():
            continue
        for name in COMMON_ENTRY_NAMES:
            if (sub / name).is_file():
                return (sub / name).relative_to(bot_dir).as_posix(), "medium"
    candidates = [
        p for p in bot_dir.glob("*.py")
        if not p.name.startswith(("test_", "smoke_", "setup", "migrate"))
    ]
    if len(candidates) == 1:
        return candidates[0].name, "low"
    return None, "none"

def _read_version(bot_dir: Path) -> str | None:
    for vf_name in ("VERSION", "VERSION.txt"):
        vf = bot_dir / vf_name
        if vf.is_file():
            v = vf.read_text(encoding="utf-8", errors="ignore").strip()
            if v:
                m = VERSION_PATTERNS[0].search(v) or VERSION_PATTERNS[1].search(v)
                return m.group(1) if m else v[:80]
    mf = bot_dir / "BOT_MANIFEST.json"
    if mf.is_file():
        try:
            v = json.loads(mf.read_text(encoding="utf-8")).get("version")
            if v and str(v).lower() != "unknown":
                return str(v)
        except Exception:
            pass
    for name in ("README.md", "README.txt", "main.py", "app.py"):
        path = bot_dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")[:20000]
            for pattern in VERSION_PATTERNS:
                m = pattern.search(text)
                if m:
                    return m.group(1)
    return None

def _classification(bot_dir: Path, entrypoint: str | None, launchers: list[str],
                    requirements: str | None, pyproject: str | None,
                    dbs: list[str], sessions: list[str], tests: list[str]) -> str:
    if entrypoint or launchers or requirements or pyproject or dbs or sessions or tests:
        return "CANONICAL"
    for p in bot_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.name in {".gitkeep", "BOT_MANIFEST.json"}:
            continue
        if p.suffix.lower() in SOURCE_SUFFIXES:
            return "CANONICAL"
    return "PLACEHOLDER"

def inspect_bot(bot_dir: Path) -> BotInfo:
    launchers = _launcher_candidates(bot_dir)
    entrypoint, confidence = _entrypoint(bot_dir, launchers)
    dbs = sorted({
        str(p.relative_to(bot_dir))
        for pat in ("*.db", "*.sqlite", "*.sqlite3")
        for p in bot_dir.rglob(pat)
        if p.is_file()
    })[:200]
    sessions = sorted(
        str(p.relative_to(bot_dir))
        for p in bot_dir.rglob("*.session")
        if p.is_file()
    )[:100]
    ignored_parts = {".venv","venv","env","__pycache__","site-packages",".git"}
    tests = sorted(
        str(p.relative_to(bot_dir))
        for p in bot_dir.rglob("test_*.py")
        if p.is_file() and not any(part.lower() in ignored_parts for part in p.relative_to(bot_dir).parts)
    )[:200]
    requirements = "requirements.txt" if (bot_dir / "requirements.txt").is_file() else None
    pyproject = "pyproject.toml" if (bot_dir / "pyproject.toml").is_file() else None
    nested = (bot_dir / bot_dir.name).is_dir()
    classification = _classification(
        bot_dir, entrypoint, launchers, requirements, pyproject, dbs, sessions, tests
    )
    return BotInfo(
        folder=bot_dir.name,
        path=str(bot_dir),
        manifest_present=(bot_dir / "BOT_MANIFEST.json").is_file(),
        version=_read_version(bot_dir),
        entrypoint=entrypoint,
        entrypoint_confidence=confidence,
        launchers=launchers,
        requirements=requirements,
        pyproject=pyproject,
        databases=dbs,
        session_files=sessions,
        test_files=tests,
        nested_duplicate_folder=nested,
        classification=classification,
    )

def discover_bots(root: Path | None = None) -> list[BotInfo]:
    root = root or project_root()
    bots = root / "bots"
    if not bots.is_dir():
        return []
    return [
        inspect_bot(p)
        for p in sorted(bots.iterdir(), key=lambda x: x.name.lower())
        if p.is_dir() and not p.name.startswith((".", "__"))
    ]

def build_inventory(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    bots = discover_bots(root)
    return {
        "schema_version": 4,
        "project_root": str(root),
        "bot_count": len(bots),
        "runnable_count": sum(1 for b in bots if b.classification == "CANONICAL"),
        "planned_count": sum(1 for b in bots if b.classification == "PLACEHOLDER"),
        "bots": [b.to_dict() for b in bots],
    }

def write_inventory(root: Path | None = None) -> Path:
    root = root or project_root()
    path = root / "state" / "vm_inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_inventory(root), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    db = PlatformDB(root=root)
    db.init()
    for b in discover_bots(root):
        db.upsert_service(
            b.folder, b.folder, b.entrypoint, b.launchers[0] if b.launchers else None
        )
    return path

def _generated_manifest(bot: BotInfo) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "name": bot.folder,
        "version": bot.version or "unknown",
        "status": "planned" if bot.classification == "PLACEHOLDER" else "existing",
        "classification": bot.classification,
        "entrypoint": bot.entrypoint,
        "entrypoint_confidence": bot.entrypoint_confidence,
        "launchers": bot.launchers,
        "requirements": bot.requirements,
        "pyproject": bot.pyproject,
        "databases": bot.databases,
        "tests": bot.test_files,
        "vm_core": {"compatible": True, "minimum_version": "1.4.0"},
    }

def create_missing_bot_manifests(root: Path | None = None, *, write: bool = False) -> list[dict[str, Any]]:
    root = root or project_root()
    out = []
    for bot in discover_bots(root):
        path = Path(bot.path) / "BOT_MANIFEST.json"
        if path.exists():
            out.append({"bot": bot.folder, "action": "preserved", "path": str(path)})
            continue
        data = _generated_manifest(bot)
        data["lifecycle"] = {"managed_by_vm": True, "auto_start": False, "auto_restart": False}
        action = "would_create"
        if write:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            action = "created"
        out.append({"bot": bot.folder, "action": action, "path": str(path), "manifest": data})
    return out

def refresh_bot_manifests(root: Path | None = None, *, write: bool = False) -> list[dict[str, Any]]:
    """Refresh generated manifest fields while preserving lifecycle/custom settings."""
    root = root or project_root()
    out = []
    for bot in discover_bots(root):
        path = Path(bot.path) / "BOT_MANIFEST.json"
        existing: dict[str, Any] = {}
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                out.append({"bot": bot.folder, "action": "skipped_invalid_existing_manifest", "path": str(path)})
                continue
        generated = _generated_manifest(bot)
        lifecycle = existing.get("lifecycle") or {
            "managed_by_vm": True, "auto_start": False, "auto_restart": False
        }
        merged = dict(existing)
        merged.update(generated)
        merged["lifecycle"] = lifecycle
        action = "would_refresh"
        if write:
            path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            action = "refreshed"
        out.append({
            "bot": bot.folder,
            "action": action,
            "classification": bot.classification,
            "path": str(path),
        })
    return out
