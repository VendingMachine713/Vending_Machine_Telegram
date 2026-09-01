"""Fail CI when canonical repository metadata drifts from the checked-in source tree."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_FILE = ROOT / "VM_PROJECT.json"


def fail(message: str) -> None:
    print(f"ERROR: {message}")
    raise SystemExit(1)


def main() -> int:
    project = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    canonical = project.get("canonical_bot_folders", [])
    if not canonical:
        fail("VM_PROJECT.json has no canonical_bot_folders")

    errors: list[str] = []
    for name in canonical:
        bot = ROOT / "bots" / name
        manifest_path = bot / "BOT_MANIFEST.json"
        if not bot.is_dir():
            errors.append(f"missing canonical bot directory: bots/{name}")
            continue
        if not manifest_path.is_file():
            errors.append(f"missing manifest: bots/{name}/BOT_MANIFEST.json")
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid manifest for {name}: {exc}")
            continue

        if manifest.get("name") != name:
            errors.append(f"{name}: manifest name mismatch")
        if manifest.get("classification") == "PLACEHOLDER":
            errors.append(f"{name}: canonical bot is still classified PLACEHOLDER")
        if manifest.get("status") == "planned":
            errors.append(f"{name}: canonical bot is still marked planned")

        entrypoint = manifest.get("entrypoint")
        if entrypoint and not (bot / entrypoint).is_file():
            errors.append(f"{name}: missing declared entrypoint {entrypoint}")

        requirements = manifest.get("requirements")
        if requirements and not (bot / requirements).is_file():
            errors.append(f"{name}: missing declared requirements {requirements}")

        for launcher in manifest.get("launchers", []):
            if not (bot / launcher).is_file():
                errors.append(f"{name}: missing declared launcher {launcher}")
        for test in manifest.get("tests", []):
            if not (bot / Path(test.replace('\\', '/'))).is_file():
                errors.append(f"{name}: missing declared test {test}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"Repository health OK: validated {len(canonical)} canonical bots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
