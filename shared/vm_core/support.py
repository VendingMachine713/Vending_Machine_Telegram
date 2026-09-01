from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import zipfile
from .paths import project_root
from .doctor import run_doctor, write_diagnostics
from .inspect import write_structure_report
from .duplicates import write_duplicate_report
from .manifests import write_inventory
from .runtime_snapshot import write_report as write_runtime_report
from .health import run_health
from .dependencies import environment_report
from .devtools import git_status
from .relationship_cleanup import write_plan as write_relationship_cleanup_plan
from .git_audit import audit as git_audit
from .storage_audit import audit as storage_audit

SECRET_PATTERNS=[
    re.compile(r'(?i)(bot[_-]?token|api[_-]?hash|password|secret)\s*[:=]\s*["\']?([^\s"\']+)'),
]

def _redact_text(text: str) -> str:
    for pat in SECRET_PATTERNS:
        text=pat.sub(lambda m:f"{m.group(1)}=[REDACTED]",text)
    return text

def _write_json(path:Path,data)->None:
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf-8")

def create_support_bundle(root: Path | None = None) -> Path:
    root=root or project_root()
    diag=root/"diagnostics"; diag.mkdir(parents=True,exist_ok=True)
    write_inventory(root)
    write_structure_report(root)
    write_duplicate_report(root)
    write_relationship_cleanup_plan(root)
    write_diagnostics(run_doctor(root),root)
    write_runtime_report(root)
    _write_json(diag/"health_live.json",run_health(root))
    _write_json(diag/"environment_live.json",environment_report(root))
    _write_json(diag/"git_status.json",git_status(root))
    _write_json(diag/"git_audit.json",git_audit(root))
    _write_json(diag/"storage_audit.json",storage_audit(root))

    try:
        from .search_index import SearchIndex
        _write_json(diag/"search_stats.json",SearchIndex(root).stats())
    except Exception as exc:
        _write_json(diag/"search_stats.json",{"error":f"{type(exc).__name__}: {exc}"})
    try:
        from .db import PlatformDB
        _write_json(diag/"open_alerts.json",PlatformDB(root=root).alerts(100))
    except Exception as exc:
        _write_json(diag/"open_alerts.json",{"error":f"{type(exc).__name__}: {exc}"})

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out=root/"state"/"support"/f"VM_SUPPORT_{stamp}.zip"
    out.parent.mkdir(parents=True,exist_ok=True)

    include=[
        root/"VM_PROJECT.json",
        diag/"latest_diagnostic.txt",diag/"latest_diagnostic.json",
        diag/"project_structure.txt",diag/"project_structure.json",
        diag/"duplicate_analysis.txt",diag/"duplicate_analysis.json",diag/"duplicate_diff.txt",
        diag/"relationship_cleanup_plan.json",
        diag/"legacy_recovery.json",
        diag/"full_validation.txt",diag/"full_validation.json",
        diag/"registry_report.json",diag/"platform_tests_report.json",
        diag/"health_report.json",diag/"health_live.json",
        diag/"environment_report.json",diag/"environment_live.json",
        diag/"preflight_report.json",diag/"supervisor_preview.json",
        diag/"search_stats.json",diag/"open_alerts.json",
        diag/"live_runtime.json",diag/"live_runtime.txt",
        diag/"git_status.json",diag/"git_audit.json",diag/"storage_audit.json",
        root/"state"/"vm_inventory.json",
    ]
    include += list((root/"bots").glob("*/BOT_MANIFEST.json"))
    logs=list((root/"logs").glob("*.jsonl"))

    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        for p in include:
            if p.is_file():
                rel=p.relative_to(root).as_posix()
                data=p.read_text(encoding="utf-8",errors="replace")
                z.writestr(rel,_redact_text(data))
        for p in logs:
            data="\n".join(p.read_text(encoding="utf-8",errors="replace").splitlines()[-500:])
            z.writestr("logs/"+p.name,_redact_text(data))
        z.writestr(
            "SUPPORT_NOTICE.txt",
            "No .env files, Telegram .session contents, private media, or live database files are included.\n"
        )
    return out


def create_support_text(root: Path | None = None) -> Path:
    root = root or project_root()
    # Refresh the same safe diagnostics used by the ZIP first.
    write_inventory(root)
    write_structure_report(root)
    write_duplicate_report(root)
    write_relationship_cleanup_plan(root)
    write_diagnostics(run_doctor(root),root)
    write_runtime_report(root)
    diag = root / "diagnostics"
    _write_json(diag/"health_live.json",run_health(root))
    _write_json(diag/"environment_live.json",environment_report(root))
    _write_json(diag/"git_status.json",git_status(root))
    _write_json(diag/"git_audit.json",git_audit(root))
    _write_json(diag/"storage_audit.json",storage_audit(root))
    try:
        from .search_index import SearchIndex
        _write_json(diag/"search_stats.json",SearchIndex(root).stats())
    except Exception as exc:
        _write_json(diag/"search_stats.json",{"error":f"{type(exc).__name__}: {exc}"})
    try:
        from .db import PlatformDB
        _write_json(diag/"open_alerts.json",PlatformDB(root=root).alerts(100))
    except Exception as exc:
        _write_json(diag/"open_alerts.json",{"error":f"{type(exc).__name__}: {exc}"})

    preferred = [
        diag/"full_validation.txt",
        diag/"full_validation.json",
        diag/"live_runtime.txt",
        diag/"live_runtime.json",
        diag/"health_live.json",
        diag/"latest_diagnostic.txt",
        diag/"latest_diagnostic.json",
        diag/"environment_live.json",
        diag/"preflight_report.json",
        diag/"platform_tests_report.json",
        diag/"supervisor_preview.json",
        diag/"search_stats.json",
        diag/"open_alerts.json",
        diag/"relationship_cleanup_plan.json",
        diag/"legacy_recovery.json",
        diag/"duplicate_analysis.txt",
        diag/"duplicate_analysis.json",
        diag/"duplicate_diff.txt",
        diag/"registry_report.json",
        diag/"git_status.json",diag/"git_audit.json",diag/"storage_audit.json",
        root/"state"/"vm_inventory.json",
    ]
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out=root/"state"/"support"/f"VM_SUPPORT_READABLE_{stamp}.txt"
    out.parent.mkdir(parents=True,exist_ok=True)
    chunks=[
        "VM SUPPORT READABLE EXPORT",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "="*78,
    ]
    for path in preferred:
        if not path.is_file():
            continue
        rel=path.relative_to(root).as_posix()
        data=_redact_text(path.read_text(encoding="utf-8",errors="replace"))
        chunks += ["","="*78,f"FILE: {rel}","="*78,data]
    out.write_text("\n".join(chunks)+"\n",encoding="utf-8")
    return out
