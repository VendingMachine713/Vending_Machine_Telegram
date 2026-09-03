from __future__ import annotations

import re
from typing import Any

BOT_TOKEN_PATTERN = re.compile(r"(?<!\d)(\d{6,12}):([A-Za-z0-9_-]{20,})(?![A-Za-z0-9_-])")


def normalize_numeric_id(value: Any) -> int | None:
    """Return a Telegram-style numeric identifier without accepting names/handles."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text or text.startswith("@"):
        return None
    if not re.fullmatch(r"-?\d+", text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def numeric_id_set(values: Any) -> set[int]:
    if values is None:
        return set()
    if isinstance(values, (str, int)):
        values = [values]
    try:
        iterator = iter(values)
    except TypeError:
        return set()
    out: set[int] = set()
    for value in iterator:
        parsed = normalize_numeric_id(value)
        if parsed is not None:
            out.add(parsed)
    return out


def redact_bot_tokens(text: str) -> str:
    """Redact Telegram Bot API token-shaped values in diagnostic text."""
    return BOT_TOKEN_PATTERN.sub("[REDACTED_TELEGRAM_BOT_TOKEN]", str(text))


def safe_peer_label(*, peer_id: Any = None, username: str | None = None, title: str | None = None) -> str:
    """Build a non-secret operator label without treating usernames as authority."""
    numeric = normalize_numeric_id(peer_id)
    if title:
        base = str(title).strip()
    elif username:
        base = "@" + str(username).lstrip("@").strip()
    else:
        base = "Telegram peer"
    return f"{base} ({numeric})" if numeric is not None else base
