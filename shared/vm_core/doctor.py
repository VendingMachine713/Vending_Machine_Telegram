from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from . import __version__
import importlib.util
import json
import os
import platform
import shutil
import sqlite3
import sys
from typing import Any
from .paths import project_root
from .manifests import discover_bots
from .db import PlatformDB
from .runtime_requirements import runtime_configuration_status
from .foundation import foundation_report

@dataclass
class Check:
    category: str
    name: str
    status: str
    detail: str
    def to_dict(self): return asdict(self)

def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)

def run_doctor(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    checks: list[Check] = []
    checks += [
        Check("platform","project_root","PASS" if root.is_dir() else "FAIL",str(root)),
        Check("platform","bots_directory","PASS" if (root/"bots").is_dir() else "FAIL",str(root/"bots")),
        Check("runtime","python","PASS" if sys.version_info >= (3,11) else "WARN",f"{platform.python_version()} | {sys.executable}"),
        Check("runtime","operating_system","PASS",f"{platform.system()} {platform.release()}"),
    ]
    free = shutil.disk_usage(root).free/(1024**3)
    checks.append(Check("runtime","disk_free","PASS" if free >= 2 else "WARN",f"{free:.1f} GiB free"))
    checks.append(Check("runtime","root_write_access","PASS" if os.access(root,os.W_OK) else "WARN","writable" if os.access(root,os.W_OK) else "not writable"))

    foundation = foundation_report(root)
    foundation_status = "PASS" if foundation["status"] == "PASS" else ("WARN" if foundation["status"] == "WARN" else "FAIL")
    checks.append(Check(
        "platform",
        "foundation_contract",
        foundation_status,
        f"contract v{foundation['contract_version']} | errors={foundation['summary']['ERROR']} warnings={foundation['summary']['WARN']}",
    ))

    for pkg in ("telethon","telegram","dotenv","tzdata"):
        found = importlib.util.find_spec(pkg) is not None
        checks.append(Check("dependencies",pkg,"PASS" if found else "INFO","installed" if found else "not installed in current Python"))

    bots = discover_bots(root)
    for b in bots:
        if b.classification == "PLACEHOLDER":
            checks.append(Check("bot",f"{b.folder}:status","INFO","PLANNED placeholder folder; runnable code is not installed yet."))
            checks.append(Check("bot",f"{b.folder}:dependencies","INFO","Not applicable until bot code is installed."))
        else:
            if b.entrypoint:
                checks.append(Check("bot",f"{b.folder}:entrypoint","PASS",f"{b.entrypoint} (confidence={b.entrypoint_confidence})"))
            elif b.launchers:
                checks.append(Check("bot",f"{b.folder}:launcher","PASS",", ".join(b.launchers)))
            else:
                checks.append(Check("bot",f"{b.folder}:entrypoint","WARN","Runnable files exist but no likely entrypoint or launcher was detected."))
            if b.requirements or b.pyproject:
                checks.append(Check("bot",f"{b.folder}:dependencies","PASS",b.pyproject or b.requirements or ""))
            else:
                checks.append(Check("bot",f"{b.folder}:dependencies","INFO","No requirements.txt or pyproject.toml at bot root."))
            cfg = runtime_configuration_status(Path(b.path))
            if cfg["required_env"] and cfg["missing_env_names"]:
                checks.append(Check("bot",f"{b.folder}:configuration","INFO","Configuration required: " + ", ".join(cfg["missing_env_names"]) + ". Values are not included in diagnostics."))
            elif cfg["required_env"]:
                checks.append(Check("bot",f"{b.folder}:configuration","PASS","Required configuration key names are present. Values are not included in diagnostics."))
        if b.nested_duplicate_folder:
            checks.append(Check("bot",f"{b.folder}:nested_duplicate","WARN",f"Nested folder '{b.folder}/{b.folder}' detected; see diagnostics/duplicate_analysis.txt. No deletion performed."))

    sessions = list(root.rglob("*.session"))
    checks.append(Check("telegram","session_files","PASS" if sessions else "INFO",f"{len(sessions)} session file(s) detected; contents not inspected."))

    sensitive_names = {".env", "secrets.json", "credentials.json"}
    invalid_json: list[tuple[str, str]] = []
    jsons = [
        p for p in root.rglob("*.json")
        if "diagnostics" not in p.parts
        and ".git" not in p.parts
        and p.name.lower() not in sensitive_names
    ]
    for p in jsons[:500]:
        try:
            json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            invalid_json.append((_safe_rel(p, root), f"{type(exc).__name__}: {exc}"))
    if invalid_json:
        detail = "; ".join(f"{path} [{err}]" for path, err in invalid_json[:10])
        checks.append(Check("config","json_syntax","WARN",f"{len(jsons[:500])} checked, {len(invalid_json)} invalid: {detail}"))
    else:
        checks.append(Check("config","json_syntax","PASS",f"{len(jsons[:500])} checked, 0 invalid"))

    pdb = PlatformDB(root=root); pdb.init()
    integ = pdb.integrity()
    checks.append(Check("database","state/vm_platform.sqlite3","PASS" if integ=="ok" else "FAIL",integ))

    active_db_files = []
    archived_db_count = 0
    archive_markers = {"backups", "archive", "updates"}
    for pat in ("*.db","*.sqlite","*.sqlite3"):
        for p in root.rglob(pat):
            rel_parts = {part.lower() for part in p.relative_to(root).parts}
            if rel_parts & archive_markers:
                archived_db_count += 1
                continue
            active_db_files.append(p)
    for p in sorted(set(active_db_files))[:60]:
        if p.resolve() == pdb.path.resolve():
            continue
        rel = _safe_rel(p, root)
        try:
            con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=2)
            try: row=con.execute("PRAGMA integrity_check").fetchone()
            finally: con.close()
            val = row[0] if row else "no result"
            checks.append(Check("database",rel,"PASS" if val=="ok" else "WARN",val))
        except sqlite3.Error as e:
            checks.append(Check("database",rel,"WARN",f"{type(e).__name__}: {e}"))
    checks.append(Check("database","archived_copies","INFO",f"{archived_db_count} database copy/copies under backups/archive/updates skipped by routine Doctor checks."))

    counts = {s: sum(1 for c in checks if c.status==s) for s in ("PASS","INFO","WARN","FAIL")}
    return {
        "schema_version":3,
        "vm_core_version":__version__,
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "project_root":str(root),
        "bot_count":len(bots),
        "runnable_count":sum(1 for b in bots if b.classification=="CANONICAL"),
        "planned_count":sum(1 for b in bots if b.classification=="PLACEHOLDER"),
        "checks":[c.to_dict() for c in checks],
        "summary":counts,
        "invalid_json_files":[{"path":p,"error":e} for p,e in invalid_json],
    }

def write_diagnostics(report: dict[str, Any], root: Path | None = None) -> tuple[Path,Path]:
    root = root or project_root()
    out = root/"diagnostics"; out.mkdir(parents=True, exist_ok=True)
    jp,tp = out/"latest_diagnostic.json", out/"latest_diagnostic.txt"
    jp.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=[
        "="*72,"VM DOCTOR","="*72,
        f"Generated: {report['generated_at_utc']}",
        f"Root:      {report['project_root']}",
        f"Bots:      {report['bot_count']} ({report['runnable_count']} runnable, {report['planned_count']} planned)",
        ""
    ]
    for c in report["checks"]:
        lines.append(f"[{c['status']:<4}] {c['category']}/{c['name']}: {c['detail']}")
    lines += ["","-"*72,"SUMMARY","-"*72]
    for s in ("PASS","INFO","WARN","FAIL"): lines.append(f"{s}: {report['summary'][s]}")
    tp.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return jp,tp
