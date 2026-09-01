from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import difflib
import hashlib
import json
import re
from typing import Any
from .paths import project_root
from .manifests import discover_bots

SKIP_NAMES={".env","secrets.json","credentials.json","config.env"}
SKIP_SUFFIXES={".session",".session-journal",".pyc",".db",".sqlite",".sqlite3"}
TEXT_SUFFIXES={".md",".txt",".ps1",".bat",".cmd",".py",".json",".toml",".yaml",".yml",".ini",".cfg"}
SECRET_PATTERNS=[
    re.compile(r'(?i)(bot[_-]?token|api[_-]?hash|password|secret)\s*[:=]\s*["\']?([^\s"\']+)'),
]

def _sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def _redact(text:str)->str:
    for pat in SECRET_PATTERNS:
        text=pat.sub(lambda m:f"{m.group(1)}=[REDACTED]",text)
    return text

def analyze_nested_duplicates(root:Path|None=None)->dict[str,Any]:
    root=root or project_root()
    report={"schema_version":3,"generated_at_utc":datetime.now(timezone.utc).isoformat(),"bots":[]}
    for bot in discover_bots(root):
        if not bot.nested_duplicate_folder: continue
        outer=Path(bot.path); nested=outer/bot.folder; rows=[]
        for np in sorted(nested.rglob("*")):
            if not np.is_file(): continue
            rel=np.relative_to(nested)
            if np.name.lower() in SKIP_NAMES or np.suffix.lower() in SKIP_SUFFIXES:
                rows.append({"relative_path":rel.as_posix(),"status":"SENSITIVE_SKIPPED","nested_size":np.stat().st_size})
                continue
            op=outer/rel; nh=_sha(np)
            if not op.is_file():
                rows.append({"relative_path":rel.as_posix(),"status":"NESTED_ONLY","nested_size":np.stat().st_size,"nested_sha256":nh})
                continue
            oh=_sha(op); same=nh==oh
            rows.append({"relative_path":rel.as_posix(),"status":"EXACT_DUPLICATE" if same else "DIFFERENT",
                         "nested_size":np.stat().st_size,"outer_size":op.stat().st_size,
                         "nested_sha256":nh,"outer_sha256":oh})
        statuses=[r["status"] for r in rows]
        exact_only=bool(rows) and all(x=="EXACT_DUPLICATE" for x in statuses)
        report["bots"].append({
            "bot":bot.folder,"nested_folder":str(nested),"safe_exact_duplicate_only":exact_only,
            "summary":{s:statuses.count(s) for s in sorted(set(statuses))},"files":rows,
            "recommendation":"Eligible for manual review before deletion; all compared files are identical."
                if exact_only else "Preserve folder. Merge DIFFERENT/NESTED_ONLY files deliberately before cleanup."
        })
    return report

def build_safe_text_diff(root:Path|None=None)->str:
    root=root or project_root()
    chunks=["="*72,"VM SAFE NESTED-FOLDER TEXT DIFF","="*72,
            "Sensitive/session/database files are excluded. Suspected secrets are redacted.",""]
    found=False
    for bot in discover_bots(root):
        if not bot.nested_duplicate_folder: continue
        outer=Path(bot.path); nested=outer/bot.folder
        for np in sorted(nested.rglob("*")):
            if not np.is_file(): continue
            rel=np.relative_to(nested); op=outer/rel
            if np.name.lower() in SKIP_NAMES or np.suffix.lower() not in TEXT_SUFFIXES: continue
            try:
                ntext=_redact(np.read_text(encoding="utf-8",errors="replace"))
                otext=_redact(op.read_text(encoding="utf-8",errors="replace")) if op.is_file() else ""
            except OSError: continue
            if op.is_file() and ntext==otext: continue
            found=True
            chunks += ["",f"### {bot.folder}: {rel.as_posix()}",
                       f"outer_exists={op.is_file()} nested_exists=True",""]
            diff=difflib.unified_diff(
                otext.splitlines(),ntext.splitlines(),
                fromfile=f"outer/{rel.as_posix()}",
                tofile=f"nested/{rel.as_posix()}",
                lineterm=""
            )
            chunks.extend(list(diff)[:2000])
    if not found: chunks.append("No safe differing text files found.")
    return "\n".join(chunks)+"\n"

def write_duplicate_report(root:Path|None=None)->tuple[Path,Path,Path]:
    root=root or project_root()
    data=analyze_nested_duplicates(root); out=root/"diagnostics"; out.mkdir(parents=True,exist_ok=True)
    jp=out/"duplicate_analysis.json"; tp=out/"duplicate_analysis.txt"; dp=out/"duplicate_diff.txt"
    jp.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["="*72,"VM NESTED DUPLICATE ANALYSIS","="*72,f"Generated: {data['generated_at_utc']}",""]
    if not data["bots"]: lines.append("No nested duplicate bot folders detected.")
    for item in data["bots"]:
        lines += [f"[{item['bot']}]",f"nested_folder={item['nested_folder']}",
                  f"safe_exact_duplicate_only={item['safe_exact_duplicate_only']}",
                  f"summary={item['summary']}",f"recommendation={item['recommendation']}"]
        for row in item["files"]: lines.append(f"  {row['status']:<18} {row['relative_path']}")
        lines.append("")
    tp.write_text("\n".join(lines)+"\n",encoding="utf-8")
    dp.write_text(build_safe_text_diff(root),encoding="utf-8")
    return jp,tp,dp
