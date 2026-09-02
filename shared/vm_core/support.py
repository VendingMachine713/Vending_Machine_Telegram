from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import re
import zipfile
from .paths import project_root
from .doctor import run_doctor, write_diagnostics
from .inspect import write_structure_report
from .duplicates import write_duplicate_report
from .manifests import write_inventory

SECRET_PATTERNS=[
    re.compile(r'(?i)(bot[_-]?token|api[_-]?hash|password|secret)\s*[:=]\s*["\']?([^\s"\']+)'),
]

def _redact_text(text: str) -> str:
    for pat in SECRET_PATTERNS:
        text=pat.sub(lambda m:f"{m.group(1)}=[REDACTED]",text)
    return text

def create_support_bundle(root: Path | None = None) -> Path:
    root=root or project_root()
    write_inventory(root)
    write_structure_report(root)
    write_duplicate_report(root)
    write_diagnostics(run_doctor(root),root)

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out=root/"state"/"support"/f"VM_SUPPORT_{stamp}.zip"
    out.parent.mkdir(parents=True,exist_ok=True)

    include=[
        root/"VM_PROJECT.json",
        root/"diagnostics"/"latest_diagnostic.txt",
        root/"diagnostics"/"latest_diagnostic.json",
        root/"diagnostics"/"project_structure.txt",
        root/"diagnostics"/"project_structure.json",
        root/"diagnostics"/"duplicate_analysis.txt",
        root/"diagnostics"/"duplicate_analysis.json",
        root/"diagnostics"/"full_validation.txt",
        root/"diagnostics"/"full_validation.json",
        root/"diagnostics"/"registry_report.json",
        root/"diagnostics"/"platform_tests_report.json",
        root/"diagnostics"/"health_report.json",
        root/"diagnostics"/"environment_report.json",
        root/"diagnostics"/"preflight_report.json",
        root/"diagnostics"/"supervisor_preview.json",
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
            "No .env files, Telegram .session contents, private media, or database files are included by this command.\n"
        )
    return out
