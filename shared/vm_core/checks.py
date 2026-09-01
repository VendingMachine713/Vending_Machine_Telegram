from __future__ import annotations
from pathlib import Path
import compileall
import os
import importlib.util
import shutil
import subprocess
import sys
from typing import Any
from .paths import project_root
from .doctor import run_doctor
from .dependencies import pip_check
from .manifests import discover_bots

def _test_env(root: Path, cwd: Path) -> dict[str,str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH","")
    entries = [str(cwd), str(root)]
    if existing:
        entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(entries)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env

def _run_suite(name: str, start_dir: Path, cwd: Path, root: Path,
               timeout: int = 90) -> dict[str,Any]:
    import tempfile
    out_path = None
    err_path = None
    proc = None
    try:
        with tempfile.NamedTemporaryFile(prefix="vm_test_out_", suffix=".txt", delete=False) as out_f, \
             tempfile.NamedTemporaryFile(prefix="vm_test_err_", suffix=".txt", delete=False) as err_f:
            out_path = Path(out_f.name)
            err_path = Path(err_f.name)
            kwargs: dict[str,Any] = {
                "cwd": cwd,
                "env": _test_env(root,cwd),
                "stdout": out_f,
                "stderr": err_f,
                "text": False,
            }
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
            else:
                kwargs["start_new_session"] = True
            proc = subprocess.Popen(
                [sys.executable,"-m","unittest","discover","-s",str(start_dir),"-p","test_*.py","-v"],
                **kwargs
            )
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill","/PID",str(proc.pid),"/T","/F"],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                else:
                    import signal
                    try:
                        os.killpg(proc.pid,signal.SIGKILL)
                    except Exception:
                        try: proc.kill()
                        except Exception: pass
                try: proc.wait(timeout=5)
                except Exception: pass
                code = "TIMEOUT"

        stdout = out_path.read_text(encoding="utf-8",errors="replace") if out_path and out_path.exists() else ""
        stderr = err_path.read_text(encoding="utf-8",errors="replace") if err_path and err_path.exists() else ""
        ok = code == 0
        return {
            "suite":name,
            "ok":ok,
            "code":code,
            "cwd":str(cwd),
            "timeout_seconds":timeout,
            "output":(stdout+stderr)[-50000:],
        }
    except Exception as exc:
        return {
            "suite":name,
            "ok":False,
            "code":"RUNNER_ERROR",
            "cwd":str(cwd),
            "output":f"{type(exc).__name__}: {exc}",
        }
    finally:
        for path in (out_path,err_path):
            if path and path.exists():
                try: path.unlink()
                except OSError: pass

def run_tests(root: Path | None = None) -> int:
    root = root or project_root()
    result = _run_suite("platform", root/"tests", root, root)
    if result["output"]:
        print(result["output"])
    return 0 if result["ok"] else 1

def run_all_tests(root: Path | None = None) -> dict[str,Any]:
    root = root or project_root()
    results = [_run_suite("platform",root/"tests",root,root)]
    for bot in discover_bots(root):
        bot_dir = Path(bot.path)
        tests = bot_dir/"tests"
        if not tests.is_dir():
            continue
        results.append(_run_suite(bot.folder,tests,bot_dir,root))
    return {
        "ok":all(x["ok"] for x in results),
        "suite_count":len(results),
        "passed_suites":sum(1 for x in results if x["ok"]),
        "failed_suites":sum(1 for x in results if not x["ok"]),
        "suites":results,
    }

def _ruff_cmd() -> list[str] | None:
    binary=shutil.which("ruff")
    if binary: return [binary]
    if importlib.util.find_spec("ruff"): return [sys.executable,"-m","ruff"]
    return None

def lint(root: Path | None = None, fix: bool = False) -> dict[str,Any]:
    root = root or project_root()
    ruff = _ruff_cmd()
    if not ruff:
        return {"available":False,"ok":True,"message":"Ruff not installed; lint skipped."}
    # Release gate checks correctness-class diagnostics, not cosmetic style.
    cmd = [*ruff,"check","--select","E9,F63,F7,F82",str(root/"shared"),str(root/"tests"),str(root/"vm.py")]
    if fix:
        cmd.append("--fix")
    r = subprocess.run(cmd,cwd=root,text=True,capture_output=True)
    return {"available":True,"ok":r.returncode==0,"code":r.returncode,
            "output":(r.stdout+r.stderr).strip()}

def format_check(root: Path | None = None) -> dict[str,Any]:
    root = root or project_root()
    ruff = _ruff_cmd()
    if not ruff:
        return {"available":False,"ok":True,"message":"Ruff not installed; format check skipped."}
    r = subprocess.run(
        [*ruff,"format","--check",str(root/"shared"),str(root/"tests"),str(root/"vm.py")],
        cwd=root,text=True,capture_output=True
    )
    return {"available":True,"ok":r.returncode==0,"code":r.returncode,
            "output":(r.stdout+r.stderr).strip()}

def full_check(root: Path | None = None, test_code: int | None = None) -> dict[str,Any]:
    root = root or project_root()
    compile_ok = compileall.compile_dir(str(root/"shared"),quiet=1) and \
                 compileall.compile_file(str(root/"vm.py"),quiet=1)
    doctor = run_doctor(root)
    pip_code,pip_output = pip_check()
    lint_result = lint(root)
    if test_code is None:
        test_code = run_tests(root)
    result = {
        "compile":bool(compile_ok),
        "platform_tests_ok":test_code==0,
        "doctor_failures":doctor["summary"]["FAIL"],
        "doctor_warnings":doctor["summary"]["WARN"],
        "pip_check_ok":pip_code==0,
        "pip_check_output":pip_output,
        "pip_check_policy":"informational_for_global_python",
        "lint":lint_result,
    }
    # Global pip conflicts are informational; VM-specific compile/tests/Doctor/lint gate release.
    result["ok"] = result["compile"] and result["platform_tests_ok"] and \
                   result["doctor_failures"]==0 and lint_result["ok"]
    return result
