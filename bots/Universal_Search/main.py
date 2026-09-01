# VM_INTELLIGENCE_RUNTIME_BRIDGE_V307
from pathlib import Path
import os, runpy, sys

BOT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BOT_ROOT.parent.parent
TARGET = (BOT_ROOT / 'Universal_Search/Universal_Search/main.py').resolve()

def main():
    if not TARGET.is_file():
        raise RuntimeError(f"Canonical runtime target missing: {TARGET}")
    runtime = TARGET.parent
    os.chdir(runtime)
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(runtime))
    runpy.run_path(str(TARGET), run_name="__main__")

if __name__ == "__main__":
    main()
