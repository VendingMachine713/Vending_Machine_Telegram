from __future__ import annotations
from pathlib import Path
import argparse,json,shutil,ast

IMPORT_BLOCK = (
    "# VM_INTELLIGENCE_V3_IMPORT_BEGIN\n"
    "from shared.vm_intelligence.admin_commands import is_intelligence_command, handle_intelligence_command\n"
    "# VM_INTELLIGENCE_V3_IMPORT_END\n"
)
DISPATCH = (
    "    # VM_INTELLIGENCE_V3_DISPATCH_BEGIN\n"
    "    if is_intelligence_command(cmd):\n"
    "        return handle_intelligence_command(cmd,args,ROOT)\n"
    "    # VM_INTELLIGENCE_V3_DISPATCH_END\n\n"
)
HELP_LINES = (
    '        "/brain - VM Intelligence executive cockpit\\n"\n'
    '        "/insights - prioritised intelligence findings\\n"\n'
    '        "/incidents - open intelligence incidents\\n"\n'
    '        "/why [service] - evidence-based root cause\\n"\n'
    '        "/performance - integrated bot performance\\n"\n'
    '        "/automation - automation opportunities\\n"\n'
    '        "/goals - operational goal status\\n"\n'
    '        "/askvm <question> - query VM Intelligence\\n"\n'
    '        "/intelhelp - all VM Intelligence commands\\n"\n'
    '        "/intelfeedback <incident_id> useful|noise - rate an Intelligence alert\\n"\n'
)

def candidates(root:Path):
    bot=root/"bots"/"Admin_Command_Centre"
    rows=[]
    for p in bot.glob("**/admin_core.py"):
        if any(x.lower() in {"backups","archive",".git","venv",".venv"} for x in p.parts):
            continue
        try:
            t=p.read_text(encoding="utf-8-sig")
        except Exception:
            continue
        if "def handle_command" in t and "shared.vm_core" in t:
            rows.append(p)
    return sorted(rows,key=lambda p:(len(p.relative_to(bot).parts),len(str(p))))

def patch_text(text:str):
    if "VM_INTELLIGENCE_V3_DISPATCH_BEGIN" in text:
        return text,False
    import_anchor="from shared.vm_core.manifests import discover_bots\n"
    if import_anchor not in text:
        raise RuntimeError("Admin import anchor not found; refusing unsafe patch.")
    text=text.replace(import_anchor,import_anchor+IMPORT_BLOCK+"\n",1)
    dispatch_anchor='    if not is_admin(user_id,cfg):\n        return "Access denied."\n\n'
    if dispatch_anchor not in text:
        raise RuntimeError("Admin authorization anchor not found; refusing unsafe patch.")
    text=text.replace(dispatch_anchor,dispatch_anchor+DISPATCH,1)
    help_anchor='        "/whoami - show your Telegram user ID\\n\\n"\n'
    if help_anchor in text:
        text=text.replace(help_anchor,help_anchor+HELP_LINES,1)
    return text,True

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--backup-dir",required=True)
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args(argv)
    root=Path(args.root).resolve();backup=Path(args.backup_dir).resolve()
    rows=candidates(root)
    if not rows:
        raise SystemExit("No compatible Admin Command Centre admin_core.py found.")
    target=rows[0]
    original=target.read_text(encoding="utf-8-sig")
    try:
        ast.parse(original, filename=str(target))
    except SyntaxError as exc:
        raise SystemExit(f"Admin source is not syntactically valid before patching: {exc}")
    patched,changed=patch_text(original)
    try:
        ast.parse(patched, filename=str(target))
    except SyntaxError as exc:
        raise SystemExit(f"Refusing Admin patch because patched source would be invalid: {exc}")
    result={"target":str(target),"changed":changed,"candidate_count":len(rows)}
    if args.apply and changed:
        rel=target.relative_to(root);dest=backup/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(target,dest)
        target.write_text(patched,encoding="utf-8")
        result["backup"]=str(dest)
    print(json.dumps(result))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
