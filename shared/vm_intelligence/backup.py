from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import json,sqlite3,zipfile,tempfile,shutil


def backup_intelligence(root):
    root=Path(root);src=root/"state"/"vm_intelligence.sqlite3"
    if not src.is_file():raise FileNotFoundError(src)
    out_dir=root/"backups";out_dir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out=out_dir/f"vm_intelligence_{stamp}.zip"
    with tempfile.TemporaryDirectory() as td:
        td=Path(td);dbcopy=td/"vm_intelligence.sqlite3"
        source=sqlite3.connect(src);dest=sqlite3.connect(dbcopy)
        try:source.backup(dest)
        finally:dest.close();source.close()
        manifest={"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
                  "source":str(src.relative_to(root)),"database_bytes":dbcopy.stat().st_size}
        (td/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
        for rel in ("config/vm_intelligence.json","diagnostics/intelligence_brief.txt","diagnostics/intelligence_report.json"):
            p=root/rel
            if p.is_file():
                d=td/rel;d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,d)
        with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
            for p in td.rglob("*"):
                if p.is_file():z.write(p,p.relative_to(td))
        with zipfile.ZipFile(out) as z:
            if z.testzip() is not None:raise RuntimeError("backup zip integrity check failed")
    return out
