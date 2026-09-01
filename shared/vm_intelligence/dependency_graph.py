from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

from .v4_schema import ensure_v4_schema


def _now(): return datetime.now(timezone.utc).isoformat()


class DependencyGraph:
    def __init__(self, store, root):
        self.store=store; self.root=Path(root); ensure_v4_schema(store)

    def build(self):
        edges=set(); bots=self.root/"bots"
        if bots.is_dir():
            for bot in bots.iterdir():
                if not bot.is_dir():continue
                for p in bot.rglob("*.py"):
                    if any(x.lower() in {"venv",".venv","__pycache__","backups","archive",".git"} for x in p.parts):continue
                    try:tree=ast.parse(p.read_text(encoding="utf-8-sig",errors="ignore"))
                    except Exception:continue
                    for node in ast.walk(tree):
                        mods=[]
                        if isinstance(node,ast.Import):mods=[x.name for x in node.names]
                        elif isinstance(node,ast.ImportFrom) and node.module:mods=[node.module]
                        for mod in mods:
                            if mod.startswith("shared.vm_core"):
                                edges.add((mod,bot.name,"imports"))
                            elif mod.startswith("shared.vm_intelligence"):
                                edges.add((mod,bot.name,"imports"))
        now=_now()
        with self.store.connect() as con:
            for src,tgt,typ in edges:
                con.execute("""INSERT INTO dependency_edges(source,target,edge_type,confidence,observed_at_utc)
                    VALUES(?,?,?,?,?) ON CONFLICT(source,target,edge_type) DO UPDATE SET observed_at_utc=excluded.observed_at_utc""",
                    (src,tgt,typ,1.0,now))
        return [{"source":a,"target":b,"edge_type":c} for a,b,c in sorted(edges)]

    def impact(self, changed_paths):
        changed=[str(x).replace("\\","/") for x in changed_paths]
        impacted=set(); reasons=[]
        with self.store.connect() as con:
            rows=[dict(r) for r in con.execute("SELECT source,target,edge_type FROM dependency_edges").fetchall()]
        for path in changed:
            module=None
            if "shared/vm_core/" in path:
                module="shared.vm_core."+Path(path).stem
            elif "shared/vm_intelligence/" in path:
                module="shared.vm_intelligence."+Path(path).stem
            if module:
                for e in rows:
                    if e["source"]==module or e["source"].startswith(module+"."):
                        impacted.add(e["target"]);reasons.append({"change":path,"service":e["target"],"dependency":e["source"]})
            if path.startswith("bots/"):
                parts=Path(path).parts
                if len(parts)>=2:impacted.add(parts[1])
        return {"services":sorted(impacted),"reasons":reasons,
                "recommended_suites":[f"{x}:canonical" for x in sorted(impacted)]}
