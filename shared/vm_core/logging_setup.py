from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any
from .paths import project_root

SENSITIVE_KEYS = {
    "token", "bot_token", "api_hash", "password", "secret", "code",
    "phone_code", "two_factor", "2fa", "authorization",
}

def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k).lower() in SENSITIVE_KEYS:
                out[k] = "[REDACTED]"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value

def log_event(event: str, *, level: str = "INFO", service: str = "platform",
              data: dict[str, Any] | None = None, root: Path | None = None) -> Path:
    root = root or project_root()
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{service}.jsonl"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "service": service,
        "event": event,
        "data": redact(data or {}),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path

def tail_logs(service: str = "platform", lines: int = 50, errors_only: bool = False,
              root: Path | None = None) -> list[str]:
    root = root or project_root()
    path = root / "logs" / f"{service}.jsonl"
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
