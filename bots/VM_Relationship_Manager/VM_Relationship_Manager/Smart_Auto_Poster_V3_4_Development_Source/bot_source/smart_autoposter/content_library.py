from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .core import create_content, content_fingerprint
from .db import Database
from .operations import set_content_tags

MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".m4v"}
_CAPTION_RE = re.compile(r"^caption(?:[ _-].*)?\.txt$", re.IGNORECASE)


def safe_id(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_").lower()
    return value or "content"


def ensure_content_structure(root: Path):
    root = Path(root)
    for sub in ("inbox", "library", "archive", "rejected"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    readme = root / "inbox" / "DROP_CONTENT_HERE.txt"
    if not readme.exists():
        readme.write_text(
            "Create one folder per advertisement. Put caption.txt plus photos/videos inside it.\n"
            "Caption files named Caption_01.txt, caption-main.txt, etc. are auto-normalized when exactly one exists.\n"
            "Optional: tags.txt with comma-separated tags.\n"
            "Then use Control Panel -> Import content inbox.\n",
            encoding="utf-8",
        )


def _read_tags(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [x.strip().lower() for x in path.read_text(encoding="utf-8-sig").replace("\n", ",").split(",") if x.strip()]


def _caption_candidate(source: Path) -> tuple[Path | None, str | None]:
    """Return the caption file and an optional normalization warning.

    Prefer a root-level file literally named caption.txt (case-insensitive). If it is
    absent, accept exactly one root-level caption*.txt-style file such as
    Caption_01.txt. Multiple candidates are intentionally rejected rather than
    guessed between.
    """
    source = Path(source)
    files = [p for p in source.iterdir() if p.is_file()]
    canonical = [p for p in files if p.name.lower() == "caption.txt"]
    if canonical:
        return canonical[0], None
    candidates = [p for p in files if _CAPTION_RE.match(p.name)]
    if len(candidates) == 1:
        return candidates[0], f"normalized caption filename from {candidates[0].name}"
    if len(candidates) > 1:
        return None, "multiple caption candidates: " + ", ".join(sorted(p.name for p in candidates))
    return None, None


def _copy_content_folder(source: Path, target: Path, caption_source: Path | None):
    """Copy an inbox item into the library while canonicalizing the caption name."""
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        # The selected caption is copied below as canonical caption.txt.
        if caption_source is not None and item.is_file() and item.resolve() == caption_source.resolve():
            continue
        destination = target / item.name
        if item.is_file():
            shutil.copy2(item, destination)
        elif item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
    if caption_source is not None:
        shutil.copy2(caption_source, target / "caption.txt")


def import_content_inbox(db: Database, root: Path, *, move: bool = True) -> list[dict]:
    root = Path(root)
    ensure_content_structure(root)
    inbox = root / "inbox"
    library = root / "library"
    rejected = root / "rejected"
    results = []
    for source in sorted(p for p in inbox.iterdir() if p.is_dir()):
        cid = safe_id(source.name)
        target = library / cid
        action = "imported"

        # Build a temporary view from source first so duplicate fingerprinting is reliable.
        caption_src, caption_note = _caption_candidate(source)
        if caption_note and caption_src is None and caption_note.startswith("multiple caption candidates"):
            dest = rejected / f"{cid}_ambiguous_caption"
            if move:
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(source), str(dest))
            results.append({"content_id": cid, "status": "rejected", "reason": caption_note})
            continue

        caption = caption_src.read_text(encoding="utf-8-sig").strip() if caption_src else ""
        media_src = [p for p in sorted(source.rglob("*")) if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS]
        if not caption and not media_src:
            dest = rejected / f"{cid}_empty"
            if move:
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(source), str(dest))
            results.append({"content_id": cid, "status": "rejected", "reason": "no caption file or supported media"})
            continue

        fp = content_fingerprint(caption, [str(p) for p in media_src])
        with db.connect() as con:
            dup = con.execute("SELECT content_id FROM content WHERE fingerprint=?", (fp,)).fetchone()
        if dup and dup["content_id"] != cid:
            dest = rejected / f"{cid}_duplicate_of_{safe_id(dup['content_id'])}"
            if move:
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(source), str(dest))
            result = {"content_id": cid, "status": "duplicate", "duplicate_of": dup["content_id"], "fingerprint": fp}
            if caption_note:
                result["caption_note"] = caption_note
            results.append(result)
            continue

        if target.exists() and any(target.iterdir()):
            use_dir = target
            action = "existing-library"
            # Existing library items keep their content. If they predate caption
            # normalization and have no canonical caption, repair it from the inbox.
            if not (use_dir / "caption.txt").exists() and caption_src is not None:
                shutil.copy2(caption_src, use_dir / "caption.txt")
        else:
            _copy_content_folder(source, target, caption_src)
            use_dir = target

        caption_file = use_dir / "caption.txt"
        caption = caption_file.read_text(encoding="utf-8-sig").strip() if caption_file.exists() else ""
        media = [p for p in sorted(use_dir.rglob("*")) if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS]
        paths = [str(p.relative_to(Path.cwd())) if p.is_relative_to(Path.cwd()) else str(p) for p in media]
        source_dir = str(use_dir.relative_to(Path.cwd())) if use_dir.is_relative_to(Path.cwd()) else str(use_dir)
        fp_final = content_fingerprint(caption, [str(p) for p in media])
        create_content(db, cid, caption, paths, source_dir=source_dir, fingerprint=fp_final)
        tags = _read_tags(use_dir / "tags.txt")
        if tags:
            set_content_tags(db, cid, add=tags, actor="content_inbox")
        if move and action == "imported":
            shutil.rmtree(source, ignore_errors=True)

        result = {
            "content_id": cid,
            "status": "ready",
            "media": len(paths),
            "caption": bool(caption),
            "tags": tags,
            "action": action,
            "fingerprint": fp_final,
        }
        if caption_src is not None:
            result["caption_source"] = caption_src.name
        if caption_note:
            result["caption_note"] = caption_note
        results.append(result)
    return results


def audit_content_library(db: Database, root: Path) -> dict:
    """Read-only content/library consistency audit for production diagnostics."""
    root = Path(root)
    ensure_content_structure(root)
    problems: list[str] = []
    warnings: list[str] = []
    items: list[dict] = []
    with db.connect() as con:
        rows = con.execute("SELECT content_id,caption,media_json,source_dir,lifecycle_state,enabled,fingerprint FROM content ORDER BY content_id").fetchall()
    fingerprints: dict[str, str] = {}
    for row in rows:
        cid = str(row["content_id"])
        try:
            media = json.loads(row["media_json"] or "[]")
        except Exception:
            media = []
            problems.append(f"{cid}: invalid media_json")
        missing = [str(x) for x in media if not Path(str(x)).exists()]
        if missing:
            problems.append(f"{cid}: {len(missing)} missing media file(s)")
        if bool(row["enabled"]) and not str(row["caption"] or "").strip():
            warnings.append(f"{cid}: enabled content has an empty caption")
        if bool(row["enabled"]) and len(media) == 0:
            warnings.append(f"{cid}: enabled content has no media")
        if len(media) > 10:
            problems.append(f"{cid}: {len(media)} media files exceed Telegram album limit 10")
        fp = str(row["fingerprint"] or "")
        if fp:
            other = fingerprints.get(fp)
            if other and other != cid:
                problems.append(f"duplicate fingerprint: {other} and {cid}")
            fingerprints[fp] = cid
        items.append({
            "content_id": cid,
            "enabled": bool(row["enabled"]),
            "state": str(row["lifecycle_state"]),
            "caption": bool(str(row["caption"] or "").strip()),
            "media": len(media),
            "missing_media": len(missing),
            "source_dir": row["source_dir"],
        })
    rejected = sorted(p.name for p in (root / "rejected").iterdir() if p.is_dir())
    return {
        "ok": not problems,
        "items": items,
        "rejected_folders": rejected,
        "problems": problems,
        "warnings": warnings,
    }
