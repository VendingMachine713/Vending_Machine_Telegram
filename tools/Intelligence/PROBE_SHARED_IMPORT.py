from __future__ import annotations
import argparse, importlib, importlib.util, json, sys
from pathlib import Path


def _inside(path_value, expected_dir: Path) -> bool:
    if not path_value:
        return False
    try:
        actual = Path(path_value).resolve()
        expected = expected_dir.resolve()
        return actual == expected or expected in actual.parents
    except Exception:
        return False


def probe(root: Path, required: list[str] | None = None) -> dict:
    root = root.resolve()
    shared_dir = root / "shared"
    vm_core_dir = shared_dir / "vm_core"
    init_file = shared_dir / "__init__.py"
    required = required or []
    result = {
        "root": str(root),
        "shared_dir_exists": shared_dir.is_dir(),
        "shared_init_exists": init_file.is_file(),
        "vm_core_dir_exists": vm_core_dir.is_dir(),
        "vm_core_init_exists": (vm_core_dir / "__init__.py").is_file(),
        "ok": False,
        "shared_origin": None,
        "vm_core_origin": None,
        "required": {},
        "error": None,
    }
    for name in list(sys.modules):
        if name == "shared" or name.startswith("shared."):
            sys.modules.pop(name, None)
    sys.path.insert(0, str(root))
    try:
        spec = importlib.util.find_spec("shared")
        result["shared_origin"] = getattr(spec, "origin", None) if spec else None
        vm_spec = importlib.util.find_spec("shared.vm_core")
        result["vm_core_origin"] = getattr(vm_spec, "origin", None) if vm_spec else None
        mod = importlib.import_module("shared.vm_core")
        result["vm_core_file"] = getattr(mod, "__file__", None)
        base_ok = _inside(getattr(mod, "__file__", None), vm_core_dir)
        required_ok = True
        for module_name in required:
            try:
                sub = importlib.import_module(module_name)
                origin = getattr(sub, "__file__", None)
                good = _inside(origin, vm_core_dir)
                result["required"][module_name] = {"ok": good, "origin": origin}
                required_ok = required_ok and good
            except Exception as exc:
                required_ok = False
                result["required"][module_name] = {
                    "ok": False,
                    "origin": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        result["ok"] = bool(base_ok and required_ok)
        if not base_ok:
            result["error"] = "shared.vm_core resolved outside the VM project"
        elif not required_ok:
            result["error"] = "one or more required VM Core submodules failed import/origin validation"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass
    return result


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--required", nargs="*", default=[])
    a = p.parse_args(argv)
    result = probe(Path(a.root), list(a.required))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
