from __future__ import annotations
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
BEGIN="# BEGIN VM PLATFORM MANAGED EXCLUSIONS"
END="# END VM PLATFORM MANAGED EXCLUSIONS"

BLOCK=r"""
.env
.env.*
!.env.example
*.session
*.session-journal
*.key
*.pem
secrets.json
credentials.json
logs/
diagnostics/
backups/
state/*.sqlite3
state/*.db
state/pids/
state/support/
state/components/
state/release_baselines/
*.log
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.ruff_cache/
media_cache/
downloads/
content/private/
"""

def main()->int:
    path=ROOT/".gitignore"
    existing=path.read_text(encoding="utf-8",errors="replace") if path.is_file() else ""
    block=BEGIN+"\n"+BLOCK.strip()+"\n"+END
    if BEGIN in existing and END in existing:
        before=existing.split(BEGIN,1)[0].rstrip()
        after=existing.split(END,1)[1].lstrip()
        new=(before+"\n\n" if before else "")+block+("\n\n"+after if after else "")+"\n"
    else:
        new=existing.rstrip()+("\n\n" if existing.strip() else "")+block+"\n"
    changed=new!=existing
    if changed:
        path.write_text(new,encoding="utf-8")
    print(f"gitignore={path}")
    print(f"changed={changed}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
