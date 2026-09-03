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

def bot_root(name: str, root: Path | None = None) -> Path:
    root = root or project_root()
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("bot name must be one folder name")
    return root / "bots" / name

def state_path(*parts: str, root: Path | None = None) -> Path:
    root = root or project_root()
    return root / "state" / Path(*parts)

def log_path(service: str = "platform", root: Path | None = None) -> Path:
    root = root or project_root()
    safe = re_safe_filename(service)
    return root / "logs" / f"{safe}.jsonl"

def re_safe_filename(value: str) -> str:
    text = str(value or "platform").strip()
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text)
    return safe or "platform"
