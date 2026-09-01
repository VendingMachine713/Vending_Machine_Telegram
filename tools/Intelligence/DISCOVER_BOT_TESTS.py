from __future__ import annotations
import argparse, json, re
from pathlib import Path

EXCLUDED_PARTS={"venv",".venv","archive","backups","__pycache__",".git","node_modules","runtime","sessions"}
FOREIGN_HINTS={
    "Smart_Auto_Poster_V2": ("smart_auto_poster","smartautoposter","smart-auto-poster"),
    "VM_Relationship_Manager": ("relationship_manager","relationship-manager","vm_relationship"),
    "Universal_Search": ("universal_search","universal-search"),
    "VM_Guard": ("vm_guard","vm-guard"),
    "Admin_Command_Centre": ("admin_command_centre","admin-command-centre"),
}

def norm(value:str)->str:
    return re.sub(r"[^a-z0-9]+","",value.lower())

def read_json(path:Path):
    try:return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:return {}

def excluded(path:Path)->bool:
    return any(part.lower() in EXCLUDED_PARTS for part in path.parts)

def foreign_source_path(path:Path,current:str)->bool:
    n=norm(str(path))
    for name,hints in FOREIGN_HINTS.items():
        if name==current:continue
        if any(norm(h) in n for h in hints):
            return True
    # Development-source copies of another bot are never canonical for the current bot.
    if current!="Smart_Auto_Poster_V2" and ("smartautoposter" in n and ("developmentsource" in n or "botsource" in n)):
        return True
    return False

def discover(root:Path,bot_name:str):
    bot=root/"bots"/bot_name
    if not bot.is_dir():
        return {"bot":bot_name,"available":False,"reason":"bot_not_found","test_dir":None,"suite_root":None,"score":None}
    candidates=[]
    direct=bot/"tests"
    if direct.is_dir():candidates.append((5000,direct,"direct_tests"))

    manifest_parents=set()
    for manifest in bot.glob("**/BOT_MANIFEST.json"):
        if excluded(manifest) or foreign_source_path(manifest,bot_name):continue
        data=read_json(manifest)
        declared=data.get("name")
        if declared not in {None,"",bot_name}:continue
        entry=data.get("entrypoint")
        entry_ok=bool(entry and (manifest.parent/entry).is_file())
        classification=str(data.get("classification") or "").upper()
        confidence=str(data.get("entrypoint_confidence") or "").lower()
        if not entry_ok and classification!="CANONICAL":
            continue
        manifest_parents.add(manifest.parent.resolve())
        t=manifest.parent/"tests"
        if t.is_dir():
            score=4500+(300 if entry_ok else 0)+(100 if classification=="CANONICAL" else 0)+(50 if confidence=="high" else 0)
            candidates.append((score,t,"manifest_tests"))

    for t in bot.glob("**/tests"):
        if not t.is_dir() or excluded(t) or foreign_source_path(t,bot_name):continue
        parent=t.parent
        score=1000
        if parent.resolve() in manifest_parents:score+=2500
        if any((parent/x).is_file() for x in ("main.py","app.py","admin_core.py")):score+=500
        # Prefer shallower paths only after canonical/runnable evidence.
        depth=len(t.relative_to(bot).parts)
        score-=min(depth,50)
        candidates.append((score,t,"discovered_tests"))

    # De-duplicate by resolved directory keeping the highest score.
    best={}
    for score,t,reason in candidates:
        key=str(t.resolve()).casefold()
        if key not in best or score>best[key][0]:best[key]=(score,t,reason)
    rows=sorted(best.values(),key=lambda x:(-x[0],len(str(x[1])),str(x[1]).casefold()))
    if not rows:
        return {"bot":bot_name,"available":False,"reason":"no_canonical_tests","test_dir":None,"suite_root":None,"score":None}
    score,t,reason=rows[0]
    return {"bot":bot_name,"available":True,"reason":reason,"test_dir":str(t.resolve()),"suite_root":str(t.parent.resolve()),"score":score,
            "candidates":[{"path":str(x[1].resolve()),"score":x[0],"reason":x[2]} for x in rows[:10]]}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--root",required=True);p.add_argument("--bot",required=True)
    a=p.parse_args(argv);result=discover(Path(a.root).resolve(),a.bot);print(json.dumps(result));return 0
if __name__=="__main__":raise SystemExit(main())
