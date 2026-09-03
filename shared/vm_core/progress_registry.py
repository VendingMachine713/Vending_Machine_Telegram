from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .autoposter_progress import smart_auto_poster_progress
from .guard_progress import vm_guard_progress
from .search_progress import universal_search_progress
from .paths import project_root
from .progress import format_progress

ProgressProvider = Callable[[Path | None], dict[str, Any]]

_PROVIDERS: dict[str, ProgressProvider] = {
    "autoposter": smart_auto_poster_progress,
    "guard": vm_guard_progress,
    "search": universal_search_progress,
}


def provider_names() -> tuple[str, ...]:
    return tuple(sorted(_PROVIDERS))


def _failed_snapshot(name: str, exc: Exception) -> dict[str, Any]:
    return {
        "headline": name.upper(),
        "overall": {
            "label": "Progress provider unavailable",
            "current": 0,
            "total": 0,
            "status": "FAILED",
            "detail": f"{type(exc).__name__}: {exc}",
            "percent": 0,
        },
        "group": None,
        "task": None,
        "services": [],
        "metrics": {},
        "events": [],
        "recovery_messages": ["Progress provider failed safely; no bot state was changed."],
    }


def progress_surface(name: str, root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    provider = _PROVIDERS.get(str(name).lower())
    if provider is None:
        raise KeyError(f"Unknown progress surface: {name}")
    try:
        return provider(root)
    except Exception as exc:
        return _failed_snapshot(str(name), exc)


def collect_progress_surfaces(root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = root or project_root()
    return {name: progress_surface(name, root) for name in _PROVIDERS}


def platform_progress_summary(root: Path | None = None) -> dict[str, Any]:
    surfaces = collect_progress_surfaces(root)
    attention_states = {"ATTENTION", "DEGRADED", "FAILED", "ERROR"}
    attention = []
    running = []
    complete = []
    for name, snapshot in surfaces.items():
        status = str((snapshot.get("overall") or {}).get("status") or "UNKNOWN").upper()
        if status in attention_states:
            attention.append(name)
        elif status in {"COMPLETE", "DONE"}:
            complete.append(name)
        else:
            running.append(name)
    return {
        "surface_count": len(surfaces),
        "attention_count": len(attention),
        "running_count": len(running),
        "complete_count": len(complete),
        "attention": attention,
        "running": running,
        "complete": complete,
        "surfaces": surfaces,
    }


def format_all_progress(root: Path | None = None) -> str:
    summary = platform_progress_summary(root)
    header = (
        "UNIVERSAL PROGRESS ENGINE\n"
        f"Surfaces: {summary['surface_count']} | Attention: {summary['attention_count']} | "
        f"Running: {summary['running_count']} | Complete: {summary['complete_count']}"
    )
    rendered = [header]
    for name in provider_names():
        rendered.append(format_progress(summary["surfaces"][name]))
    return "\n\n".join(rendered)
