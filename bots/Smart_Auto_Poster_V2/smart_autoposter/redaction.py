from __future__ import annotations

import re

BOT_TOKEN = re.compile(r"\b\d{6,14}:AA[A-Za-z0-9_-]{15,}\b")
API_HASH = re.compile(r"\b[a-fA-F0-9]{32}\b")
PHONE = re.compile(r"(?<!\d)\+\d{9,15}(?!\d)")
LOGIN_CODE = re.compile(r"(?i)(login code|code you received|2fa password)\s*[:=]\s*\S+")


def redact_text(value: str | None) -> str | None:
    if value is None: return None
    text = str(value)
    text = BOT_TOKEN.sub("[REDACTED_BOT_TOKEN]", text)
    text = API_HASH.sub("[REDACTED_API_HASH]", text)
    text = PHONE.sub("[REDACTED_PHONE]", text)
    text = LOGIN_CODE.sub(lambda m: m.group(1) + ": [REDACTED]", text)
    return text
