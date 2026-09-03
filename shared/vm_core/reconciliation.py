from __future__ import annotations

from pathlib import Path
import hashlib
from typing import Any

from .source_of_truth import classify_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not root.is_dir():
        return result
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if classify_path(rel) not in {"sensitive", "generated"}:
                result[rel] = path
    return result


def compare_nested_bot(root: Path, bot_name: str) -> dict[str, Any]:
    """Compare a canonical bot directory with a same-name nested legacy copy.

    This function is deliberately read-only. It never deletes, moves, archives, commits,
    or rewrites files. It produces the evidence needed for a later approval-gated cleanup.
    """
    outer = root / "bots" / bot_name
    nested = outer / bot_name
    if not outer.is_dir():
        return {"ok": False, "reason": "canonical_missing", "bot": bot_name}
    if not nested.is_dir():
        return {
            "ok": True,
            "bot": bot_name,
            "nested_exists": False,
            "exact_duplicates": [],
            "different": [],
            "outer_only": [],
            "nested_only": [],
            "safe_to_archive_after_review": True,
        }

    outer_files = _files(outer)
    # Do not recursively treat the nested tree as part of canonical outer content.
    outer_files = {
        rel: path for rel, path in outer_files.items()
        if not rel.startswith(bot_name + "/")
    }
    nested_files = _files(nested)

    exact: list[str] = []
    different: list[dict[str, Any]] = []
    outer_only = sorted(set(outer_files) - set(nested_files))
    nested_only = sorted(set(nested_files) - set(outer_files))

    for rel in sorted(set(outer_files) & set(nested_files)):
        outer_hash = _sha256(outer_files[rel])
        nested_hash = _sha256(nested_files[rel])
        if outer_hash == nested_hash:
            exact.append(rel)
        else:
            different.append({
                "path": rel,
                "outer_sha256": outer_hash,
                "nested_sha256": nested_hash,
                "outer_size": outer_files[rel].stat().st_size,
                "nested_size": nested_files[rel].stat().st_size,
            })

    blockers = []
    if nested_only:
        blockers.append("nested_unique_files_require_review")
    if different:
        blockers.append("different_files_require_review")

    return {
        "ok": True,
        "bot": bot_name,
        "nested_exists": True,
        "outer": outer.relative_to(root).as_posix(),
        "nested": nested.relative_to(root).as_posix(),
        "exact_duplicates": exact,
        "different": different,
        "outer_only": outer_only,
        "nested_only": nested_only,
        "blockers": blockers,
        "safe_to_archive_after_review": not nested_only and not different,
        "destructive_action_performed": False,
    }
