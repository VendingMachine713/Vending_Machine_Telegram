from __future__ import annotations
from pathlib import Path
import json, os
from typing import Any

def _env_key_names(path: Path) -> set[str]:
    keys=set()
    if not path.is_file(): return keys
    try:
        for raw in path.read_text(encoding='utf-8',errors='ignore').splitlines():
            line=raw.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            k,v=line.split('=',1)
            if k.strip() and v.strip(): keys.add(k.strip())
    except OSError: pass
    return keys

def load_manifest(bot_dir: Path) -> dict[str,Any]:
    p=bot_dir/'BOT_MANIFEST.json'
    if not p.is_file(): return {}
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return {}

def runtime_configuration_status(bot_dir: Path) -> dict[str,Any]:
    m=load_manifest(bot_dir); req=m.get('runtime_requirements') or {}
    required=[str(x) for x in req.get('env',[])]
    local=_env_key_names(bot_dir/'.env')
    present=[k for k in required if os.getenv(k) or k in local]
    missing=[k for k in required if k not in present]
    return {'required_env':required,'present_env_names':present,'missing_env_names':missing,'configured':not missing}
