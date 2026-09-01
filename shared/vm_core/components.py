from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any
from .paths import project_root


def _dir(root: Path) -> Path:
    p = root / "state" / "components"
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_component(service: str, data: dict[str, Any], root: Path | None = None) -> Path:
    root = root or project_root()
    payload = {
        "schema_version": 1,
        "service": service,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        **data,
    }
    path = _dir(root) / f"{service}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def read_components(root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = root or project_root()
    out: dict[str, dict[str, Any]] = {}
    p = _dir(root)
    for path in p.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            service = str(data.get("service") or path.stem)
            out[service] = data
        except Exception:
            continue
    return out
