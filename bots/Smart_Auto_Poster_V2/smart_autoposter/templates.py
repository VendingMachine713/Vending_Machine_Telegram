from __future__ import annotations

from dataclasses import dataclass

from .core import create_campaign
from .scheduler import configure_daily, configure_interval


@dataclass(frozen=True)
class CampaignTemplate:
    key: str
    description: str
    priority: int
    rotation: str
    reuse_minutes: int
    conflict_minutes: int
    spread_minutes: int
    schedule_mode: str
    schedule_value: object | None


TEMPLATES = {
    "evergreen": CampaignTemplate("evergreen", "Steady recurring campaign", 50, "sequential", 0, 60, 20, "interval", 360),
    "daily": CampaignTemplate("daily", "Twice-daily campaign", 50, "sequential", 0, 60, 20, "daily", ["09:00", "18:00"]),
    "announcement": CampaignTemplate("announcement", "High-priority manual announcement", 90, "sequential", 0, 0, 5, "manual", None),
    "one_off": CampaignTemplate("one_off", "One-off campaign; set its date/time after creation", 80, "sequential", 0, 30, 10, "manual", None),
    "rotating_ads": CampaignTemplate("rotating_ads", "Recurring multi-variant rotation", 60, "least_recent", 720, 60, 30, "interval", 240),
}


def list_templates() -> list[dict]:
    return [vars(x) for x in TEMPLATES.values()]


def create_from_template(db, template_key: str, campaign_id: str, name: str, content_id: str, *, tags: str = "", exclude_tags: str = "", timezone_name: str = "Australia/Adelaide"):
    key = template_key.strip().lower()
    if key not in TEMPLATES:
        raise ValueError("Unknown template: " + template_key)
    t = TEMPLATES[key]
    create_campaign(
        db, campaign_id, name, content_id, priority=t.priority, tags=tags, exclude_tags=exclude_tags,
        rotation_mode=t.rotation, min_content_reuse_seconds=t.reuse_minutes * 60,
        conflict_gap_seconds=t.conflict_minutes * 60, spread_seconds=t.spread_minutes * 60,
    )
    if t.schedule_mode == "interval":
        configure_interval(db, campaign_id, int(t.schedule_value) * 60, timezone_name)
    elif t.schedule_mode == "daily":
        configure_daily(db, campaign_id, list(t.schedule_value), None, timezone_name)
    return t
