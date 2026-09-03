from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
from typing import Any

SENSITIVE_SUFFIXES = {
    ".session", ".session-journal", ".pem", ".key", ".p12", ".pfx",
    ".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm",
    ".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm",
}
SENSITIVE_BASENAMES = {
    ".env", "credentials.json", "secrets.json", "secret.json",
    "token.json", "tokens.json",
}
GENERATED_DIR_NAMES = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "logs", "log", "diagnostics", "backups", "runtime", "cache",
}
RUNTIME_TOP_LEVEL = {"state", "logs", "diagnostics", "backups"}
SOURCE_EXTENSIONS = {
    ".py", ".ps1", ".bat", ".cmd", ".md", ".txt", ".json", ".toml",
    ".yaml", ".yml", ".ini", ".cfg", ".csv",
}
CANONICAL_BOTS = (
    "Smart_Auto_Poster_V2",
    "VM_Guard",
    "Universal_Search",
    "Admin_Command_Centre",
    "VM_Relationship_Manager",
)


@dataclass
class GitCommandResult:
    ok: bool
    code: int
    stdout: str
    stderr: str


def _run_git(root: Path, *args: str) -> GitCommandResult:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, timeout=60
        )
        return GitCommandResult(
            proc.returncode == 0, proc.returncode, proc.stdout, proc.stderr.strip()
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitCommandResult(False, 127, "", f"{type(exc).__name__}: {exc}")


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("./")


def classify_path(rel: str) -> str:
    """Classify a repository-relative path without reading file contents."""
    norm = _norm(rel)
    p = Path(norm)
    parts = tuple(x.lower() for x in p.parts)
    base = p.name.lower()
    suffix = p.suffix.lower()

    if base in {".env.example", ".env.sample", ".env.template"}:
        return "source"
    if base in SENSITIVE_BASENAMES or base.startswith(".env."):
        return "sensitive"
    if suffix in SENSITIVE_SUFFIXES:
        return "sensitive"
    if base.endswith(".session") or base.endswith(".session-journal"):
        return "sensitive"
    if any(part in GENERATED_DIR_NAMES for part in parts):
        return "generated"
    if parts and parts[0] in RUNTIME_TOP_LEVEL:
        return "generated"
    if base.endswith((".log", ".tmp", ".temp", ".bak")):
        return "generated"
    if suffix in SOURCE_EXTENSIONS or base in {
        ".gitignore", "dockerfile", "makefile", "requirements.txt"
    }:
        return "source"
    return "review"


def tracked_policy_violations(root: Path) -> dict[str, list[str]]:
    result = _run_git(root, "ls-files", "-z")
    if not result.ok:
        return {
            "critical": [], "generated": [], "review": [],
            "error": [result.stderr or "git ls-files failed"],
        }
    paths = [p for p in result.stdout.split("\x00") if p]
    critical: list[str] = []
    generated: list[str] = []
    review: list[str] = []
    for rel in paths:
        cls = classify_path(rel)
        if cls == "sensitive":
            critical.append(rel)
        elif cls == "generated":
            generated.append(rel)
        elif cls == "review":
            review.append(rel)
    return {
        "critical": sorted(critical),
        "generated": sorted(generated),
        "review": sorted(review),
        "error": [],
    }


def working_tree(root: Path) -> dict[str, Any]:
    result = _run_git(root, "status", "--porcelain=v1", "-z")
    if not result.ok:
        return {"ok": False, "entries": [], "error": result.stderr}
    raw = [x for x in result.stdout.split("\x00") if x]
    entries: list[dict[str, str]] = []
    i = 0
    while i < len(raw):
        item = raw[i]
        status = item[:2]
        path = item[3:] if len(item) >= 4 else item
        entry: dict[str, str] = {
            "status": status,
            "path": path,
            "class": classify_path(path),
        }
        if status and status[0] in {"R", "C"} and i + 1 < len(raw):
            i += 1
            entry["from"] = raw[i]
        entries.append(entry)
        i += 1
    return {"ok": True, "entries": entries, "error": ""}


def _version_from_text(text: str) -> str | None:
    for pattern in (
        r"(?im)^\s*Build:\s*([0-9]+(?:\.[0-9]+){1,3}(?:[-+._A-Za-z0-9]*)?)\s*$",
        r"(?im)^\s*Version:\s*([0-9]+(?:\.[0-9]+){1,3}(?:[-+._A-Za-z0-9]*)?)\s*$",
        r"(?im)^\s*([0-9]+(?:\.[0-9]+){1,3}(?:[-+._A-Za-z0-9]*)?)\s*$",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def bot_version_evidence(root: Path, bot: str) -> dict[str, Any]:
    bot_dir = root / "bots" / bot
    result: dict[str, Any] = {
        "bot": bot, "exists": bot_dir.is_dir(), "evidence": {}, "consistent": True
    }
    if not bot_dir.is_dir():
        return result

    version_file = bot_dir / "VERSION.txt"
    if version_file.is_file():
        version = _version_from_text(
            version_file.read_text(encoding="utf-8-sig", errors="replace")
        )
        if version:
            result["evidence"]["VERSION.txt"] = version

    manifest = bot_dir / "BOT_MANIFEST.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
            if data.get("version"):
                result["evidence"]["BOT_MANIFEST.json"] = str(data["version"])
        except (OSError, json.JSONDecodeError):
            result["evidence"]["BOT_MANIFEST.json"] = "INVALID_JSON"

    values = {v for v in result["evidence"].values() if v != "INVALID_JSON"}
    result["consistent"] = (
        len(values) <= 1 and "INVALID_JSON" not in result["evidence"].values()
    )
    result["canonical_version"] = next(iter(values)) if len(values) == 1 else None
    return result


def duplicate_bot_folders(root: Path) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    bots = root / "bots"
    if not bots.is_dir():
        return found
    for outer in bots.iterdir():
        if not outer.is_dir():
            continue
        nested = outer / outer.name
        if nested.is_dir():
            found.append({
                "bot": outer.name,
                "outer": outer.relative_to(root).as_posix(),
                "nested": nested.relative_to(root).as_posix(),
            })
    return sorted(found, key=lambda item: item["bot"].lower())


def git_state(root: Path) -> dict[str, Any]:
    branch = _run_git(root, "branch", "--show-current")
    head = _run_git(root, "rev-parse", "HEAD")
    origin = _run_git(root, "remote", "get-url", "origin")
    remote_head = GitCommandResult(False, 1, "", "")
    if branch.ok and branch.stdout.strip():
        remote_head = _run_git(
            root, "rev-parse", f"refs/remotes/origin/{branch.stdout.strip()}"
        )
    ahead_behind = None
    if head.ok and remote_head.ok:
        ab = _run_git(
            root, "rev-list", "--left-right", "--count",
            f"{remote_head.stdout.strip()}...{head.stdout.strip()}"
        )
        if ab.ok:
            try:
                behind, ahead = [int(x) for x in ab.stdout.split()]
                ahead_behind = {"ahead": ahead, "behind": behind}
            except ValueError:
                pass
    return {
        "branch": branch.stdout.strip() if branch.ok else None,
        "local_head": head.stdout.strip() if head.ok else None,
        "origin": origin.stdout.strip() if origin.ok else None,
        "remote_tracking_head": remote_head.stdout.strip() if remote_head.ok else None,
        "ahead_behind": ahead_behind,
    }


def source_check(root: Path) -> dict[str, Any]:
    root = root.resolve()
    git_root = _run_git(root, "rev-parse", "--show-toplevel")
    is_repo = git_root.ok
    policy = tracked_policy_violations(root) if is_repo else {
        "critical": [], "generated": [], "review": [], "error": ["not a git repository"]
    }
    tree = working_tree(root) if is_repo else {
        "ok": False, "entries": [], "error": "not a git repository"
    }
    versions = [bot_version_evidence(root, name) for name in CANONICAL_BOTS]
    duplicates = duplicate_bot_folders(root)

    source_changes = [
        item for item in tree["entries"] if item["class"] in {"source", "review"}
    ]
    generated_changes = [
        item for item in tree["entries"] if item["class"] == "generated"
    ]
    sensitive_changes = [
        item for item in tree["entries"] if item["class"] == "sensitive"
    ]
    inconsistent_versions = [
        item["bot"] for item in versions if item["exists"] and not item["consistent"]
    ]

    blockers: list[str] = []
    if not is_repo:
        blockers.append("not_git_repo")
    if policy["critical"]:
        blockers.append("sensitive_files_tracked")
    if sensitive_changes:
        blockers.append("sensitive_working_tree_paths")
    if duplicates:
        blockers.append("nested_duplicate_bot_folders")
    if inconsistent_versions:
        blockers.append("version_mismatch")
    if source_changes:
        blockers.append("uncommitted_source_changes")

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "is_git_repo": is_repo,
        "git": git_state(root) if is_repo else {},
        "tracked_policy": policy,
        "working_tree": {
            "source_or_review": source_changes,
            "generated": generated_changes,
            "sensitive": sensitive_changes,
            "total": len(tree["entries"]),
        },
        "bot_versions": versions,
        "duplicate_bot_folders": duplicates,
        "blockers": blockers,
        "status": "REVIEW" if blockers else "VERIFIED",
    }


def format_source_check(report: dict[str, Any]) -> str:
    git = report.get("git", {})
    tree = report.get("working_tree", {})
    policy = report.get("tracked_policy", {})
    lines = [
        "=" * 72,
        " VM SOURCE OF TRUTH CHECK",
        "=" * 72,
        f"Status             : {report.get('status')}",
        f"Git repository     : {'YES' if report.get('is_git_repo') else 'NO'}",
        f"Branch             : {git.get('branch') or '-'}",
        f"Local HEAD         : {(git.get('local_head') or '-')[:12]}",
        f"Remote tracking    : {(git.get('remote_tracking_head') or '-')[:12]}",
        f"Source changes     : {len(tree.get('source_or_review', []))}",
        f"Generated changes  : {len(tree.get('generated', []))}",
        f"Sensitive changes  : {len(tree.get('sensitive', []))}",
        f"Tracked sensitive  : {len(policy.get('critical', []))}",
        f"Duplicate bots     : {len(report.get('duplicate_bot_folders', []))}",
    ]
    if report.get("blockers"):
        lines.append("Blockers           : " + ", ".join(report["blockers"]))
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_source_snapshot(root: Path, destination: Path | None = None) -> dict[str, Any]:
    """Create a source-only local safety snapshot.

    Sensitive and generated runtime files are intentionally excluded. The manifest
    records what was omitted. This helper never commits, pushes, deletes, resets,
    merges or changes branches.
    """
    root = root.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = destination or (root / "backups" / f"pre_source_of_truth_{stamp}")
    destination.mkdir(parents=True, exist_ok=False)

    tracked = _run_git(root, "ls-files", "-z")
    if not tracked.ok:
        raise RuntimeError(tracked.stderr or "git ls-files failed")

    copied: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    missing: list[str] = []
    for rel in [x for x in tracked.stdout.split("\x00") if x]:
        cls = classify_path(rel)
        src = root / rel
        if cls in {"sensitive", "generated"}:
            excluded.append({"path": rel, "class": cls})
            continue
        if not src.is_file():
            missing.append(rel)
            continue
        dst = destination / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append({
            "path": rel,
            "sha256": _sha256(dst),
            "size": dst.stat().st_size,
        })

    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "source_check": source_check(root),
        "copied": copied,
        "excluded": excluded,
        "missing": missing,
    }
    manifest_path = destination / "SOURCE_SNAPSHOT_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "ok": True,
        "path": str(destination),
        "manifest": str(manifest_path),
        "copied_files": len(copied),
        "excluded_files": len(excluded),
        "missing_files": len(missing),
    }
