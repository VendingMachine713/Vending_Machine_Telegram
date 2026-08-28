from __future__ import annotations
from pathlib import Path
import compileall
import shutil
import subprocess
import sys
from typing import Any
from .paths import project_root
from .doctor import run_doctor
from .dependencies import pip_check

def run_tests(root: Path | None = None) -> int:
    root=root or project_root()
    return subprocess.call([sys.executable,"-m","unittest","discover","-s",str(root/"tests"),"-p","test_*.py","-v"],cwd=root)

def lint(root: Path | None = None, fix: bool = False) -> dict[str,Any]:
    root=root or project_root()
    ruff=shutil.which("ruff")
    if not ruff:
        return {"available":False,"ok":True,"message":"Ruff not installed; lint skipped."}
    cmd=[ruff,"check",str(root/"shared"),str(root/"tests"),str(root/"vm.py")]
    if fix: cmd.append("--fix")
    r=subprocess.run(cmd,cwd=root,text=True,capture_output=True)
    return {"available":True,"ok":r.returncode==0,"code":r.returncode,"output":(r.stdout+r.stderr).strip()}

def format_check(root: Path | None = None) -> dict[str,Any]:
    root=root or project_root()
    ruff=shutil.which("ruff")
    if not ruff: return {"available":False,"ok":True,"message":"Ruff not installed; format check skipped."}
    r=subprocess.run([ruff,"format","--check",str(root/"shared"),str(root/"tests"),str(root/"vm.py")],cwd=root,text=True,capture_output=True)
    return {"available":True,"ok":r.returncode==0,"code":r.returncode,"output":(r.stdout+r.stderr).strip()}

def full_check(root: Path | None = None, test_code: int | None = None) -> dict[str,Any]:
    root=root or project_root()
    compile_ok=compileall.compile_dir(str(root/"shared"),quiet=1) and compileall.compile_file(str(root/"vm.py"),quiet=1)
    doctor=run_doctor(root)
    pip_code,pip_output=pip_check()
    lint_result=lint(root)
    if test_code is None:
        test_code=run_tests(root)
    result={
        "compile":bool(compile_ok),
        "platform_tests_ok":test_code==0,
        "doctor_failures":doctor["summary"]["FAIL"],
        "doctor_warnings":doctor["summary"]["WARN"],
        "pip_check_ok":pip_code==0,
        "pip_check_output":pip_output,
        "pip_check_policy":"warning_only_because_global_python_can_contain_unrelated_packages",
        "lint":lint_result,
    }
    result["ok"]=result["compile"] and result["platform_tests_ok"] and result["doctor_failures"]==0 and lint_result["ok"]
    return result
