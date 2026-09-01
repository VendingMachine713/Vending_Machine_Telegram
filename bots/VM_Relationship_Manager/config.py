
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parent
MASTER_DIR = BOT_DIR.parent.parent
ENV_PATH = BOT_DIR / ".env"
def _load_local_env() -> None:
    """Load the bot-local .env deterministically, including Windows UTF-8 BOM files."""
    if not ENV_PATH.exists():
        raise RuntimeError(f"Missing .env file: {ENV_PATH}")
    # `utf-8-sig` transparently strips a BOM if Windows PowerShell wrote one.
    # `override=True` ensures the bot-local file wins over stale/blank inherited
    # process variables from a parent shell.
    load_dotenv(dotenv_path=ENV_PATH, override=True, encoding="utf-8-sig")


_load_local_env()


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _int_list(value: str) -> set[int]:
    out: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            out.add(int(part))
    return out


def _resolve_path(env_name: str, default: Path) -> Path:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return default
    path = Path(raw)
    if not path.is_absolute():
        path = BOT_DIR / path
    return path.resolve()


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    phone: str
    bot_token: str
    admin_ids: set[int]
    session_name: str
    database_path: Path
    backup_dir: Path
    log_dir: Path
    timezone: ZoneInfo
    daily_digest_hour: int
    weekly_digest_weekday: int
    weekly_digest_hour: int


def load_settings() -> Settings:
    # Re-read the local file so configuration changes made by supported helper
    # scripts are picked up without relying on module-import timing.
    _load_local_env()
    db_default = MASTER_DIR / "shared" / "exports" / "VM_Relationship_Manager" / "vm_relationships.db"
    backup_default = MASTER_DIR / "shared" / "backups" / "VM_Relationship_Manager"
    log_default = MASTER_DIR / "shared" / "logs" / "VM_Relationship_Manager"
    session_default = str(BOT_DIR / "runtime" / "vm_relationship_user")

    settings = Settings(
        api_id=int(_required("TELEGRAM_API_ID")),
        api_hash=_required("TELEGRAM_API_HASH"),
        phone=os.getenv("TELEGRAM_PHONE", "").strip(),
        bot_token=_required("BOT_TOKEN"),
        admin_ids=_int_list(_required("ADMIN_IDS")),
        session_name=os.getenv("SESSION_NAME", session_default).strip(),
        database_path=_resolve_path("DATABASE_PATH", db_default),
        backup_dir=_resolve_path("BACKUP_DIR", backup_default),
        log_dir=_resolve_path("LOG_DIR", log_default),
        timezone=ZoneInfo(os.getenv("TIMEZONE", "Australia/Adelaide")),
        daily_digest_hour=int(os.getenv("DAILY_DIGEST_HOUR", "9")),
        # python-telegram-bot: Sunday=0, Monday=1, ... Saturday=6
        weekly_digest_weekday=int(os.getenv("WEEKLY_DIGEST_WEEKDAY", "1")),
        weekly_digest_hour=int(os.getenv("WEEKLY_DIGEST_HOUR", "9")),
    )

    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    Path(settings.session_name).parent.mkdir(parents=True, exist_ok=True)
    return settings
