from __future__ import annotations

import re
import shutil
from pathlib import Path

from .core import create_content, content_fingerprint
from .db import Database
from .operations import set_content_tags

MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".m4v"}


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
            "Optional: tags.txt with comma-separated tags.\n"
            "Then use Control Panel -> Import content inbox.\n",
            encoding="utf-8",
        )


def _read_tags(path: Path) -> list[str]:
    if not path.exists(): return []
    return [x.strip().lower() for x in path.read_text(encoding="utf-8-sig").replace("\n", ",").split(",") if x.strip()]


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
        caption_src = source / "caption.txt"
        caption = caption_src.read_text(encoding="utf-8-sig").strip() if caption_src.exists() else ""
        media_src = [p for p in sorted(source.rglob("*")) if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS]
        if not caption and not media_src:
            dest = rejected / f"{cid}_empty"
            if move:
                if dest.exists(): shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(source), str(dest))
            results.append({"content_id": cid, "status": "rejected", "reason": "no caption.txt or supported media"})
            continue
        fp = content_fingerprint(caption, [str(p) for p in media_src])
        with db.connect() as con:
            dup = con.execute("SELECT content_id FROM content WHERE fingerprint=?", (fp,)).fetchone()
        if dup and dup["content_id"] != cid:
            dest = rejected / f"{cid}_duplicate_of_{safe_id(dup['content_id'])}"
            if move:
                if dest.exists(): shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(source), str(dest))
            results.append({"content_id": cid, "status": "duplicate", "duplicate_of": dup["content_id"], "fingerprint": fp})
            continue

        if target.exists() and any(target.iterdir()):
            use_dir = target
            action = "existing-library"
        else:
            target.mkdir(parents=True, exist_ok=True)
            for item in source.iterdir():
                destination = target / item.name
                if item.is_file(): shutil.copy2(item, destination)
                elif item.is_dir(): shutil.copytree(item, destination, dirs_exist_ok=True)
            use_dir = target

        caption_file = use_dir / "caption.txt"
        caption = caption_file.read_text(encoding="utf-8-sig").strip() if caption_file.exists() else ""
        media = [p for p in sorted(use_dir.rglob("*")) if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS]
        paths = [str(p.relative_to(Path.cwd())) if p.is_relative_to(Path.cwd()) else str(p) for p in media]
        source_dir = str(use_dir.relative_to(Path.cwd())) if use_dir.is_relative_to(Path.cwd()) else str(use_dir)
        fp_final = content_fingerprint(caption, [str(p) for p in media])
        create_content(db, cid, caption, paths, source_dir=source_dir, fingerprint=fp_final)
        tags = _read_tags(use_dir / "tags.txt")
        if tags: set_content_tags(db, cid, add=tags, actor="content_inbox")
        if move and action == "imported": shutil.rmtree(source, ignore_errors=True)
        results.append({"content_id": cid, "status": "ready", "media": len(paths), "caption": bool(caption), "tags": tags,
                        "action": action, "fingerprint": fp_final})
    return results
