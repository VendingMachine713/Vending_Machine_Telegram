from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def clamp_percent(value: float | int | None) -> float:
    """Clamp a percentage to the inclusive 0..100 range."""
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, number))


def percent_from_ratio(current: float | int, total: float | int) -> float:
    """Return an exact percentage for a current/total pair."""
    try:
        total_value = float(total)
        current_value = float(current)
    except (TypeError, ValueError):
        return 0.0
    if total_value <= 0:
        return 0.0
    return clamp_percent((current_value / total_value) * 100.0)


def transfer_percent(sent: float | int, total: float | int) -> float:
    """Normalize Telegram/Telethon transfer progress to 0..100 percent."""
    return percent_from_ratio(sent, total)


def render_bar(percent: float | int, width: int = 20, *, filled: str = "🟩", empty: str = "⬜") -> str:
    """Render a bar whose filled cells correlate with the numeric percentage."""
    width = max(1, int(width))
    pct = clamp_percent(percent)
    filled_cells = int((pct * width) // 100)
    if pct >= 100:
        filled_cells = width
    return f"{filled * filled_cells}{empty * (width - filled_cells)} {pct:.0f}%"


def plain_status(stage: str, *, error: str | None = None) -> str:
    """Convert internal progress stages into concise operator-facing wording."""
    stage = (stage or "unknown").strip().lower()
    labels = {
        "queued": "Waiting in queue",
        "claimed": "Starting this group",
        "preparing": "Preparing post",
        "uploading": "Uploading media to Telegram",
        "sending_text": "Sending text to Telegram",
        "awaiting_confirmation": "Waiting for Telegram confirmation",
        "recording_delivery": "Recording confirmed delivery",
        "sent": "Posted successfully",
        "deferred": "Waiting before retrying",
        "retrying": "A retry is scheduled",
        "failed": "Posting failed",
        "uncertain": "Delivery needs verification; automatic retry blocked",
        "quarantined": "Destination temporarily quarantined",
        "cancelled": "Posting cancelled",
        "expired": "Posting expired",
        "paused": "Posting is paused",
    }
    text = labels.get(stage, stage.replace("_", " ").strip().capitalize() or "Unknown")
    if error:
        return f"{text} — {str(error).strip()}"
    return text


@dataclass(frozen=True)
class GroupProgress:
    job_id: int
    campaign_id: str
    group_id: int
    group_name: str
    stage: str
    percent: float
    status: str
    error: str | None = None

    @classmethod
    def build(
        cls,
        *,
        job_id: int,
        campaign_id: str,
        group_id: int,
        group_name: str,
        stage: str,
        percent: float | int,
        error: str | None = None,
    ) -> "GroupProgress":
        return cls(
            job_id=int(job_id),
            campaign_id=str(campaign_id),
            group_id=int(group_id),
            group_name=str(group_name),
            stage=str(stage),
            percent=clamp_percent(percent),
            status=plain_status(stage, error=error),
            error=str(error) if error else None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "campaign_id": self.campaign_id,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "stage": self.stage,
            "percent": self.percent,
            "status": self.status,
            "error": self.error,
        }
