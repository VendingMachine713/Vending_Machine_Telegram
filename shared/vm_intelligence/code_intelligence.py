from __future__ import annotations
from pathlib import Path
from collections import defaultdict
import ast

SKIP={"venv",".venv","__pycache__","backups","archive",".git","runtime","data","logs","state"}

class CodeIntelligence:
    def __init__(self, root): self.root=Path(root)

    def _files(self):
        bots=self.root/"bots"
        if not bots.exists(): return []
        return [p for p in bots.rglob("*.py") if not any(part.lower() in SKIP for part in p.parts)]

    def build(self):
        deps=defaultdict(set);parse_errors=[];nodes=[];edges=[];functions=0;classes=0;tests=defaultdict(list)
        for p in self._files():
            rel=str(p.relative_to(self.root)).replace("\\","/")
            parts=p.relative_to(self.root/"bots").parts
            bot=parts[0] if parts else "unknown"
            nodes.append({"id":rel,"bot":bot,"kind":"test" if ("tests" in p.parts or p.name.startswith("test_")) else "module"})
            if "tests" in p.parts or p.name.startswith("test_"): tests[bot].append(rel)
            try:tree=ast.parse(p.read_text(encoding="utf-8-sig",errors="ignore"),filename=rel)
            except Exception as exc:
                parse_errors.append({"file":rel,"error":type(exc).__name__});continue
            for node in ast.walk(tree):
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):functions+=1
                elif isinstance(node,ast.ClassDef):classes+=1
                elif isinstance(node,ast.Import):
                    for n in node.names:
                        deps[bot].add(n.name);edges.append({"from":rel,"to":n.name,"type":"imports"})
                elif isinstance(node,ast.ImportFrom) and node.module:
                    deps[bot].add(node.module);edges.append({"from":rel,"to":node.module,"type":"imports"})
        return {"python_modules":len(nodes),"functions":functions,"classes":classes,
                "nodes":nodes,"edges":edges,"dependencies":{k:sorted(v) for k,v in sorted(deps.items())},
                "tests":{k:sorted(v) for k,v in sorted(tests.items())},"parse_errors":parse_errors[:50]}

    def snapshot(self): return self.build()

    def test_plan(self, changed_sources):
        snap=self.build();rows=[]
        for source in sorted(set(changed_sources)):
            rows.append({"source":source,"tests":snap["tests"].get(source,[]),
                         "strategy":"all_source_tests" if snap["tests"].get(source) else "platform_regression_only"})
        return rows
