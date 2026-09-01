from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

MANAGED_PATHS = (
    "vm.py",
    "VM_PROJECT.json",
    "pyproject.toml",
    "shared",
    "config/vm_platform.json",
    "VM_CONTROL.bat",
    "START_VM_MANAGED.bat",
    "ENABLE_VM_AUTOSTART.ps1",
    "ENABLE_VM_AUTOSTART.bat",
    "DISABLE_VM_AUTOSTART.ps1",
    "DISABLE_VM_AUTOSTART.bat",
    "bots/Admin_Command_Centre",
    "bots/Universal_Search",
    "bots/VM_Guard",
)


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if path.is_file():
        return {path.name: _hash(path)}
    out: dict[str, str] = {}
    for p in sorted(path.rglob("*")):
        if p.is_file():
            out[p.relative_to(path).as_posix()] = _hash(p)
    return out


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _remove(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _safety_backup(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = root / "backups" / f"pre_manual_snapshot_restore_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    for rel in MANAGED_PATHS:
        src = root / rel
        if src.exists():
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            _copy(src, dst)
    return out


def restore(root: Path, snapshot: Path, *, apply: bool = False,
            make_safety_backup: bool = True) -> dict[str, Any]:
    root = root.resolve()
    snapshot = snapshot.resolve()
    if not snapshot.is_dir():
        return {"ok": False, "applied": False, "reason": "snapshot directory does not exist", "snapshot": str(snapshot)}
    if not snapshot.name.startswith("pre_v1_4_ecosystem_"):
        return {"ok": False, "applied": False, "reason": "snapshot name is not an expected pre-v1.4 snapshot", "snapshot": str(snapshot)}

    actions = []
    for rel in MANAGED_PATHS:
        src = snapshot / rel
        dst = root / rel
        actions.append({
            "path": rel,
            "snapshot_present": src.exists(),
            "current_present": dst.exists(),
            "action": "restore" if src.exists() else ("remove_new" if dst.exists() else "none"),
        })

    report: dict[str, Any] = {
        "ok": True,
        "applied": False,
        "root": str(root),
        "snapshot": str(snapshot),
        "actions": actions,
    }
    if not apply:
        return report

    safety = _safety_backup(root) if make_safety_backup else None
    for item in actions:
        rel = item["path"]
        src = snapshot / rel
        dst = root / rel
        _remove(dst)
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            _copy(src, dst)

    verification = []
    verified = True
    for rel in MANAGED_PATHS:
        src = snapshot / rel
        dst = root / rel
        if src.exists():
            same = _files(src) == _files(dst)
        else:
            same = not dst.exists()
        verification.append({"path": rel, "matches_snapshot": same})
        verified = verified and same

    report.update({
        "ok": verified,
        "applied": True,
        "safety_backup": str(safety) if safety else None,
        "verification": verification,
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore VM platform-managed files from a pre-v1.4 snapshot.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-safety-backup", action="store_true")
    args = parser.parse_args()
    result = restore(
        Path(args.root), Path(args.snapshot), apply=args.apply,
        make_safety_backup=not args.no_safety_backup,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
