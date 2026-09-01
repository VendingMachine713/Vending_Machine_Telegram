from __future__ import annotations
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.paths import project_root

def audit_universal_search(root: Path) -> dict:
    path = root / "bots" / "Universal_Search" / "core.py"
    if not path.is_file():
        return {"file":str(path),"present":False}
    text = path.read_text(encoding="utf-8-sig",errors="replace")
    return {
        "file":str(path),
        "present":True,
        "has_conn_method":bool(re.search(r"(?m)^\\s*def\\s+conn\\s*\\(",text)),
        "has_contextmanager_conn":"@contextmanager" in text,
        "note":"Audit only. VM v1.4 does not rewrite unknown legacy core.py code automatically.",
    }

def main()->int:
    print(json.dumps(audit_universal_search(project_root()),indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
