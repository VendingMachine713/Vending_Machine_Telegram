from __future__ import annotations
import argparse, importlib, json, os, sys, unittest
from pathlib import Path

def prepare_path(root:Path,suite_root:Path,bot_root:Path|None=None):
    ordered=[root,suite_root]
    if bot_root:ordered.append(bot_root)
    # Explicit path insertion is used instead of relying on PYTHONPATH inherited by Windows Store Python.
    resolved=[str(p.resolve()) for p in ordered if p]
    sys.path[:]=[x for x in sys.path if str(Path(x or '.').resolve()) not in set(resolved)]
    for p in reversed(resolved):sys.path.insert(0,p)


def verify_vm_core(root:Path):
    for name in list(sys.modules):
        if name == "shared" or name.startswith("shared."):
            sys.modules.pop(name, None)
    mod=importlib.import_module("shared.vm_core")
    actual=Path(getattr(mod,"__file__","")).resolve()
    expected=(root/"shared"/"vm_core").resolve()
    if expected not in actual.parents and actual != expected/"__init__.py":
        raise RuntimeError(f"shared.vm_core resolved outside VM project: {actual}; expected under {expected}")

def iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_tests(item)
        else:
            yield item

def test_ids(suite):
    return sorted({t.id() for t in iter_tests(suite)})


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--suite-root',required=True)
    p.add_argument('--test-dir',required=True);p.add_argument('--bot-root');p.add_argument('--pattern',default='test_*.py');p.add_argument('--result-json')
    a=p.parse_args(argv)
    root=Path(a.root).resolve();suite_root=Path(a.suite_root).resolve();test_dir=Path(a.test_dir).resolve()
    bot_root=Path(a.bot_root).resolve() if a.bot_root else None
    prepare_path(root,suite_root,bot_root)
    try:
        verify_vm_core(root)
    except Exception as exc:
        print(f"[TEST-RUNNER] VM Core import verification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"[TEST-RUNNER] root={root}", file=sys.stderr)
        print(f"[TEST-RUNNER] shared_init={(root/'shared'/'__init__.py').is_file()} vm_core_init={(root/'shared'/'vm_core'/'__init__.py').is_file()}", file=sys.stderr)
        return 3
    os.chdir(suite_root)
    suite=unittest.defaultTestLoader.discover(str(test_dir),pattern=a.pattern,top_level_dir=None)
    ids=test_ids(suite)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    failed=sorted({t.id() for t,_ in result.failures})
    errors=sorted({t.id() for t,_ in result.errors})
    skipped=sorted({t.id() for t,_ in result.skipped})
    payload={
        "ok":result.wasSuccessful(),
        "tests_run":result.testsRun,
        "test_count_discovered":len(ids),
        "test_ids":ids,
        "failed_test_ids":failed,
        "error_test_ids":errors,
        "skipped_test_ids":skipped,
    }
    if a.result_json:
        out=Path(a.result_json).resolve();out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding="utf-8")
    return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
