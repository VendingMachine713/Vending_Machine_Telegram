from __future__ import annotations
from pathlib import Path
import shutil, subprocess, sys
from typing import Any
from .paths import project_root

def status()->dict[str,Any]: return {'ruff':shutil.which('ruff'),'uv':shutil.which('uv'),'git':shutil.which('git'),'python':sys.executable}

def install(apply:bool=False)->dict[str,Any]:
    missing=[x for x in ('ruff','uv') if not shutil.which(x)]
    if not missing: return {'ok':True,'changed':False,'status':status()}
    cmd=[sys.executable,'-m','pip','install','--user',*missing]
    if not apply: return {'ok':True,'dry_run':True,'missing':missing,'command':cmd}
    r=subprocess.run(cmd,text=True,capture_output=True)
    return {'ok':r.returncode==0,'dry_run':False,'code':r.returncode,'output':(r.stdout+r.stderr)[-10000:],'status':status()}

def git_status(root:Path|None=None)->dict[str,Any]:
    root=root or project_root(); git=shutil.which('git')
    if not git: return {'available':False}
    inside=subprocess.run([git,'rev-parse','--is-inside-work-tree'],cwd=root,text=True,capture_output=True)
    if inside.returncode!=0: return {'available':True,'repository':False}
    branch=subprocess.run([git,'branch','--show-current'],cwd=root,text=True,capture_output=True).stdout.strip()
    remotes=subprocess.run([git,'remote','-v'],cwd=root,text=True,capture_output=True).stdout.strip().splitlines()
    changes=[x for x in subprocess.run([git,'status','--porcelain'],cwd=root,text=True,capture_output=True).stdout.splitlines() if x.strip()]
    return {'available':True,'repository':True,'branch':branch,'remote_lines':remotes,'working_tree_changes':len(changes)}
