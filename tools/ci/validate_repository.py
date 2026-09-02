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


def _validate_admin_separation(errors: list[str]) -> None:
    """Prevent Smart Auto Poster from silently reclaiming Telegram admin ownership."""
    poster = ROOT / "bots" / "Smart_Auto_Poster_V2"
    settings_path = poster / "smart_autoposter" / "settings.py"
    env_example = poster / ".env.example"
    admin_manifest = ROOT / "bots" / "Admin_Command_Centre" / "BOT_MANIFEST.json"

    if not settings_path.is_file():
        errors.append("Smart_Auto_Poster_V2: missing smart_autoposter/settings.py for admin separation check")
    else:
        settings = settings_path.read_text(encoding="utf-8-sig", errors="ignore")
        marker = "def admin_bot_enabled"
        if marker not in settings:
            errors.append("Smart_Auto_Poster_V2: missing admin_bot_enabled separation guard")
        else:
            tail = settings.split(marker, 1)[1][:900]
            if "return False" not in tail:
                errors.append(
                    "Smart_Auto_Poster_V2: embedded Telegram admin can be enabled; "
                    "Admin_Command_Centre must remain the single admin surface"
                )

    if env_example.is_file():
        env_text = env_example.read_text(encoding="utf-8-sig", errors="ignore")
        forbidden = (
            "ADMIN_BOT_TOKEN=",
            "ADMIN_USER_IDS=",
            "ADMIN_READONLY_USER_IDS=",
            "ADMIN_BOT_SESSION=",
        )
        for key in forbidden:
            if key in env_text:
                errors.append(
                    f"Smart_Auto_Poster_V2/.env.example: forbidden embedded-admin setting {key[:-1]}"
                )

    if not admin_manifest.is_file():
        errors.append("Admin_Command_Centre: missing BOT_MANIFEST.json for ownership check")
    else:
        try:
            manifest = json.loads(admin_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Admin_Command_Centre: invalid manifest during ownership check: {exc}")
        else:
            capabilities = set(manifest.get("capabilities", []))
            if "smart_auto_poster_control" not in capabilities:
                errors.append(
                    "Admin_Command_Centre: manifest must declare smart_auto_poster_control capability"
                )


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

    _validate_admin_separation(errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"Repository health OK: validated {len(canonical)} canonical bots and admin ownership boundary.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
