from __future__ import annotations

from pathlib import Path


def project_root(start: Path | None = None) -> Path:
    """Locate the Vending_Machine_Telegram root without depending on cwd."""
    candidates: list[Path] = []
    if start is not None:
        candidates.append(Path(start).resolve())

    candidates.append(Path(__file__).resolve())
    candidates.append(Path.cwd().resolve())

    for candidate in candidates:
        current = candidate if candidate.is_dir() else candidate.parent
        for parent in (current, *current.parents):
            if (parent / "bots").is_dir() and (
                (parent / "vm.py").exists()
                or parent.name.lower() == "vending_machine_telegram"
                or (parent / "VM_PROJECT.json").exists()
            ):
                return parent

    # The packaged layout is deterministic: shared/vm_core/paths.py -> project root
    return Path(__file__).resolve().parents[2]


def ensure_platform_dirs(root: Path) -> None:
    for relative in (
        "shared",
        "tools",
        "tests",
        "config",
        "logs",
        "backups",
        "docs",
        "releases",
        "diagnostics",
        "state",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
