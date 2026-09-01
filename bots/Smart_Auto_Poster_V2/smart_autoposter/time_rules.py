from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_hhmm(value: str) -> time:
    try:
        h, m = value.strip().split(":", 1)
        h, m = int(h), int(m)
    except Exception as exc:
        raise ValueError(f"Invalid HH:MM value: {value!r}") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Invalid HH:MM value: {value!r}")
    return time(h, m)


def quiet_until(now_utc: datetime, start: str | None, end: str | None, timezone_name: str) -> datetime | None:
    """Return the UTC end of the active quiet period, or None when posting is allowed."""
    if not start or not end:
        return None
    s, e = parse_hhmm(start), parse_hhmm(end)
    if s == e:
        raise ValueError("quiet_start and quiet_end cannot be identical")
    tz = ZoneInfo(timezone_name)
    local = now_utc.astimezone(tz)
    current = local.time().replace(tzinfo=None)

    if s < e:  # same-day quiet period
        if not (s <= current < e):
            return None
        end_local = datetime.combine(local.date(), e, tzinfo=tz)
    else:  # overnight, e.g. 22:00 -> 07:00
        if current >= s:
            end_local = datetime.combine(local.date() + timedelta(days=1), e, tzinfo=tz)
        elif current < e:
            end_local = datetime.combine(local.date(), e, tzinfo=tz)
        else:
            return None
    return end_local.astimezone(timezone.utc)
