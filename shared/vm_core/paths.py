from __future__ import annotations
from pathlib import Path

STANDARD_DIRS = (
    "shared", "tools", "tests", "config", "logs", "backups", "docs",
    "releases", "diagnostics", "state", "state/pids",
    "state/release_baselines", "state/support",
)

def project_root(start: Path | None = None) -> Path:
    candidates = []
    if start:
        candidates.append(Path(start).resolve())
    candidates.extend([Path(__file__).resolve(), Path.cwd().resolve()])

    for candidate in candidates:
        current = candidate if candidate.is_dir() else candidate.parent
        for parent in (current, *current.parents):
            if (parent / "bots").is_dir() and (
                (parent / "vm.py").exists()
                or (parent / "VM_PROJECT.json").exists()
                or parent.name.lower() == "vending_machine_telegram"
            ):
                return parent
    return Path(__file__).resolve().parents[2]

def ensure_platform_dirs(root: Path) -> None:
    for rel in STANDARD_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)

def relative_display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)
