from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any

from .paths import project_root, log_path
from .telegram_helpers import redact_bot_tokens

SENSITIVE_KEY_PARTS = {
    "token", "api_hash", "password", "secret", "credential", "authorization",
    "phone_code", "two_factor", "2fa",
}

def _sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)

def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[k] = "[REDACTED]" if _sensitive_key(k) else redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact(v) for v in value)
    if isinstance(value, str):
        return redact_bot_tokens(value)
    return value

def log_event(event: str, *, level: str = "INFO", service: str = "platform",
              data: dict[str, Any] | None = None, root: Path | None = None) -> Path:
    root = root or project_root()
    path = log_path(service, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": str(level or "INFO").upper(),
        "service": str(service or "platform"),
        "event": str(event or "unknown"),
        "data": redact(data or {}),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return path

def tail_logs(service: str = "platform", lines: int = 50, errors_only: bool = False,
              root: Path | None = None) -> list[str]:
    root = root or project_root()
    path = log_path(service, root)
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if errors_only:
        filtered = []
        for line in raw:
            try:
                obj = json.loads(line)
                if obj.get("level") in {"ERROR", "CRITICAL", "WARN", "WARNING"}:
                    filtered.append(line)
            except json.JSONDecodeError:
                pass
        raw = filtered
    return raw[-max(1, lines):]
