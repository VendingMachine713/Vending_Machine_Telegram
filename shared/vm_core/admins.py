from __future__ import annotations
from pathlib import Path
import json
from typing import Any
from .paths import project_root

def admins_path(root: Path | None = None) -> Path:
    root = root or project_root()
    return root / "config" / "vm_admins.json"

def load_admin_ids(root: Path | None = None) -> set[int]:
    path = admins_path(root)
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {int(x) for x in data.get("telegram_user_ids", [])}
    except Exception:
        return set()

def save_admin_ids(ids: set[int], root: Path | None = None) -> Path:
    path = admins_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1, "telegram_user_ids": sorted(ids)}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path

def add_admin_id(user_id: int, root: Path | None = None) -> Path:
    ids = load_admin_ids(root)
    ids.add(int(user_id))
    return save_admin_ids(ids, root)
