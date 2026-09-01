from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeliveryProgress:
    job_id: int
    group_id: int
    group_name: str
    stage: str
    percent: int
    message: str
    account_key: str | None = None
    problem: str | None = None
    bytes_sent: int | None = None
    bytes_total: int | None = None


def clamp_percent(value: int | float) -> int:
    return max(0, min(100, int(round(value))))


def text_bar(percent: int, width: int = 10) -> str:
    """Green filled progress bar for the Telegram/admin status view."""
    pct = clamp_percent(percent)
    width = max(5, int(width))
    filled = int(round(width * pct / 100))
    return f"{'🟩' * filled}{'⬜' * (width - filled)} {pct}%"


def plain_stage(stage: str) -> str:
    return {
        "queued": "Waiting its turn",
        "checking": "Checking group and account",
        "preparing": "Preparing photos and caption",
        "uploading": "Uploading media",
        "confirming": "Confirming Telegram accepted the post",
        "deferred": "Moved aside; other groups continue",
        "retry": "Waiting to retry automatically",
        "sent": "Posted successfully",
        "failed": "Could not post",
        "uncertain": "Needs verification before retry",
    }.get(stage, stage.replace("_", " ").strip().title())
