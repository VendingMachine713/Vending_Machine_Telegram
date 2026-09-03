from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

PROJECT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

def _load_project_env() -> None:
    # Unit/integration tests can explicitly disable project .env loading so a
    # real production .env cannot overwrite temporary DATABASE_PATH/content
    # fixtures.  Production behavior remains unchanged unless this opt-in test
    # flag is set.
    if os.getenv("SMART_AUTOPOSTER_DISABLE_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    # The project-local .env is authoritative for this bot.  override=True
    # prevents stale Windows/user environment variables from shadowing edits.
    load_dotenv(dotenv_path=PROJECT_ENV_PATH, override=True)

_load_project_env()


def _path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default).strip())


def _csv_ints(name: str) -> tuple[int, ...]:
    out = []
    for raw in os.getenv(name, "").replace(";", ",").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(int(raw))
        except ValueError:
            pass
    return tuple(dict.fromkeys(out))


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    primary_session: str
    secondary_session: str
    database_path: Path
    config_csv: Path
    timezone: str
    primary_staging_chat_id: int | None
    secondary_staging_chat_id: int | None
    media_cache_dir: Path
    backup_dir: Path
    log_dir: Path
    min_send_gap_seconds: int
    send_timeout_seconds: int
    runtime_lock_path: Path
    auth_refresh_seconds: int
    circuit_breaker_failures: int
    circuit_breaker_window_minutes: int
    circuit_breaker_pause_minutes: int
    circuit_breaker_failure_ratio: float
    auto_backup_hours: int
    auto_backup_keep: int
    content_root: Path
    auto_rescan_minutes: int
    daily_summary_hours: int
    weekly_summary_hours: int
    # V2.4 unattended operations
    admin_bot_token: str
    admin_user_ids: tuple[int, ...]
    admin_readonly_user_ids: tuple[int, ...]
    admin_bot_session: str
    admin_bot_persist_session: bool
    admin_notifications_min_severity: str
    watchdog_seconds: int
    heartbeat_stale_seconds: int
    network_check_host: str
    network_check_port: int
    reconnect_initial_seconds: int
    reconnect_max_seconds: int
    max_queue_size: int
    max_pending_per_campaign: int
    max_pending_per_destination: int
    queue_history_days: int
    event_retention_days: int
    log_retention_days: int
    diagnostics_dir: Path
    update_dir: Path
    maintenance_hours: int
    recommendations_hours: int
    auto_apply_rules_on_scan: bool

    @classmethod
    def load(cls, require_credentials: bool = False) -> "Settings":
        _load_project_env()
        api_id_raw = os.getenv("TELEGRAM_API_ID", "").strip()
        api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
        if require_credentials and (not api_id_raw or not api_hash):
            raise RuntimeError("Missing TELEGRAM_API_ID / TELEGRAM_API_HASH in .env")
        api_id = int(api_id_raw) if api_id_raw else 0
        return cls(
            api_id=api_id,
            api_hash=api_hash,
            primary_session=os.getenv("PRIMARY_SESSION", "runtime/sessions/my_account").strip(),
            secondary_session=os.getenv("SECONDARY_SESSION", "runtime/sessions/Auto_Post_Secondary").strip(),
            database_path=_path("DATABASE_PATH", "data/smart_autoposter.sqlite3"),
            config_csv=_path("CONFIG_CSV", "config/telegram_recommended_config.csv"),
            timezone=os.getenv("DEFAULT_TIMEZONE", "Australia/Adelaide").strip(),
            primary_staging_chat_id=int(os.getenv("PRIMARY_STAGING_CHAT_ID")) if os.getenv("PRIMARY_STAGING_CHAT_ID", "").strip() else None,
            secondary_staging_chat_id=int(os.getenv("SECONDARY_STAGING_CHAT_ID")) if os.getenv("SECONDARY_STAGING_CHAT_ID", "").strip() else None,
            media_cache_dir=_path("MEDIA_CACHE_DIR", "data/cache"),
            backup_dir=_path("BACKUP_DIR", "backups"),
            log_dir=_path("LOG_DIR", "logs"),
            min_send_gap_seconds=max(0, int(os.getenv("MIN_SEND_GAP_SECONDS", "3"))),
            send_timeout_seconds=max(15, int(os.getenv("SEND_TIMEOUT_SECONDS", "45"))),
            runtime_lock_path=_path("RUNTIME_LOCK_PATH", "runtime/telegram_runtime.lock"),
            auth_refresh_seconds=max(30, int(os.getenv("AUTH_REFRESH_SECONDS", "300"))),
            circuit_breaker_failures=max(1, int(os.getenv("CIRCUIT_BREAKER_FAILURES", "10"))),
            circuit_breaker_window_minutes=max(1, int(os.getenv("CIRCUIT_BREAKER_WINDOW_MINUTES", "10"))),
            circuit_breaker_pause_minutes=max(1, int(os.getenv("CIRCUIT_BREAKER_PAUSE_MINUTES", "30"))),
            circuit_breaker_failure_ratio=min(1.0, max(0.0, float(os.getenv("CIRCUIT_BREAKER_FAILURE_RATIO", "0.80")))),
            auto_backup_hours=max(0, int(os.getenv("AUTO_BACKUP_HOURS", "24"))),
            auto_backup_keep=max(1, int(os.getenv("AUTO_BACKUP_KEEP", "14"))),
            content_root=_path("CONTENT_ROOT", "content"),
            auto_rescan_minutes=max(0, int(os.getenv("AUTO_RESCAN_MINUTES", "360"))),
            daily_summary_hours=max(1, int(os.getenv("DAILY_SUMMARY_HOURS", "24"))),
            weekly_summary_hours=max(24, int(os.getenv("WEEKLY_SUMMARY_HOURS", "168"))),
            admin_bot_token=os.getenv("ADMIN_BOT_TOKEN", "").strip(),
            admin_user_ids=_csv_ints("ADMIN_USER_IDS"),
            admin_readonly_user_ids=_csv_ints("ADMIN_READONLY_USER_IDS"),
            admin_bot_session=os.getenv("ADMIN_BOT_SESSION", "runtime/admin_bot").strip(),
            admin_bot_persist_session=os.getenv("ADMIN_BOT_PERSIST_SESSION", "0").strip().lower() in {"1","true","yes","on"},
            admin_notifications_min_severity=os.getenv("ADMIN_NOTIFICATIONS_MIN_SEVERITY", "IMPORTANT").strip().upper(),
            watchdog_seconds=max(5, int(os.getenv("WATCHDOG_SECONDS", "30"))),
            heartbeat_stale_seconds=max(30, int(os.getenv("HEARTBEAT_STALE_SECONDS", "180"))),
            network_check_host=os.getenv("NETWORK_CHECK_HOST", "telegram.org").strip() or "telegram.org",
            network_check_port=max(1, min(65535, int(os.getenv("NETWORK_CHECK_PORT", "443")))),
            reconnect_initial_seconds=max(5, int(os.getenv("RECONNECT_INITIAL_SECONDS", "15"))),
            reconnect_max_seconds=max(30, int(os.getenv("RECONNECT_MAX_SECONDS", "300"))),
            max_queue_size=max(100, int(os.getenv("MAX_QUEUE_SIZE", "50000"))),
            max_pending_per_campaign=max(10, int(os.getenv("MAX_PENDING_PER_CAMPAIGN", "10000"))),
            max_pending_per_destination=max(1, int(os.getenv("MAX_PENDING_PER_DESTINATION", "100"))),
            queue_history_days=max(7, int(os.getenv("QUEUE_HISTORY_DAYS", "180"))),
            event_retention_days=max(7, int(os.getenv("EVENT_RETENTION_DAYS", "90"))),
            log_retention_days=max(7, int(os.getenv("LOG_RETENTION_DAYS", "30"))),
            diagnostics_dir=_path("DIAGNOSTICS_DIR", "diagnostics"),
            update_dir=_path("UPDATE_DIR", "updates"),
            maintenance_hours=max(1, int(os.getenv("MAINTENANCE_HOURS", "24"))),
            recommendations_hours=max(1, int(os.getenv("RECOMMENDATIONS_HOURS", "24"))),
            auto_apply_rules_on_scan=os.getenv("AUTO_APPLY_RULES_ON_SCAN", "0").strip().lower() in {"1","true","yes","on"},
        )

    @property
    def sessions(self) -> dict[str, str]:
        return {"primary": self.primary_session, "secondary": self.secondary_session}

    @property
    def staging_chats(self) -> dict[str, int | None]:
        return {"primary": self.primary_staging_chat_id, "secondary": self.secondary_staging_chat_id}

    @property
    def admin_bot_enabled(self) -> bool:
        return bool(self.admin_bot_token and (self.admin_user_ids or self.admin_readonly_user_ids) and self.api_id and self.api_hash)

    def ensure_dirs(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_csv.parent.mkdir(parents=True, exist_ok=True)
        Path(self.primary_session).parent.mkdir(parents=True, exist_ok=True)
        Path(self.secondary_session).parent.mkdir(parents=True, exist_ok=True)
        Path(self.admin_bot_session).parent.mkdir(parents=True, exist_ok=True)
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.content_root.mkdir(parents=True, exist_ok=True)
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        self.update_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("inbox", "library", "archive", "rejected"):
            (self.content_root / sub).mkdir(parents=True, exist_ok=True)
        for sub in ("inbox", "applied", "failed", "backups"):
            (self.update_dir / sub).mkdir(parents=True, exist_ok=True)
