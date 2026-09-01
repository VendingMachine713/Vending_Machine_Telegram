from __future__ import annotations
from pathlib import Path
from typing import Any
from .paths import project_root
from .db import PlatformDB
from .logging_setup import log_event

def emit(event_type: str, source: str = "manual", payload: dict[str,Any] | None = None, root: Path | None = None) -> int:
    root=root or project_root()
    db=PlatformDB(root=root); db.init()
    eid=db.add_event(event_type,source,payload)
    log_event("event_emitted",data={"event_id":eid,"event_type":event_type,"source":source},root=root)
    return eid
