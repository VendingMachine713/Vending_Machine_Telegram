import html
from datetime import datetime

from match_ui import money


def _short(value, limit=140):
    value = str(value or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _date_only(value):
    if not value:
        return "unknown"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.date().isoformat()
    except (TypeError, ValueError):
        return str(value)[:10]


def message_link(row):
    username = (row["chat_username"] or "").lstrip("@") if "chat_username" in row.keys() else ""
    if username:
        return f"https://t.me/{username}/{row['message_id']}"
    chat_id = str(row["chat_id"])
    if chat_id.startswith("-100") and len(chat_id) > 4:
        return f"https://t.me/c/{chat_id[4:]}/{row['message_id']}"
    return None


def format_wtb_expiry_alert(row, *, expires_utc=None):
    title = html.escape(_short(row["title"] or "Wanted listing", 120))
    budget = html.escape(money(row["price_cents"]))
    location = row["location_hint"] if "location_hint" in row.keys() else None
    lines = [
        "⏳ <b>WTB check-in</b>",
        "",
        f"<b>{title}</b>",
        f"Budget: {budget}",
    ]
    if location:
        lines.append(f"Location: {html.escape(_short(location, 80))}")
    if expires_utc:
        lines.append(f"Expiry window: {_date_only(expires_utc)}")
    lines.extend(
        [
            "",
            "This wanted post is still indexed as active. Review it if the demand has been filled or changed.",
        ]
    )
    link = message_link(row)
    if link:
        lines.append(f'<a href="{html.escape(link, quote=True)}">Open original WTB post</a>')
    return "\n".join(lines)[:3900]


def format_demand_stats(stats):
    calibration = stats.get("calibration") or {}
    current = calibration.get("current") or {}
    categories = stats.get("categories") or {}
    queue = stats.get("expiry_alert_queue") or {}
    average = money(stats.get("average_budget_cents")) if stats.get("average_budget_cents") is not None else "unknown"

    lines = [
        "<b>Demand intelligence</b>",
        f"Active WTB: {stats.get('active_wtb', 0)}",
        f"Matched: {stats.get('matched_wtb', 0)} | Unmatched: {stats.get('unmatched_wtb', 0)}",
        f"Average stated budget: {html.escape(average)}",
        f"Expiring within 7d: {stats.get('expiring_within_7d', 0)}",
        f"Overdue reminder state: {stats.get('overdue_reminder', 0)}",
        f"Event backlog: {stats.get('event_backlog', 0)}",
    ]
    if categories:
        lines.append("Top demand categories: " + ", ".join(
            f"{html.escape(str(k).replace('_', ' '))}={v}" for k, v in categories.items()
        ))
    if queue:
        lines.append("WTB reminder queue: " + " ".join(f"{k}={v}" for k, v in sorted(queue.items())))

    lines.append("")
    lines.append("<b>Match calibration</b>")
    lines.append(
        f"Labelled feedback: {calibration.get('labelled', 0)} "
        f"(+{calibration.get('positive', 0)} / -{calibration.get('negative', 0)})"
    )
    precision = current.get("precision")
    precision_text = "n/a" if precision is None else f"{precision:.0%}"
    lines.append(
        f"Current threshold: {current.get('threshold', 65):.0f} | "
        f"precision: {precision_text} ({current.get('samples', 0)} labelled at/above threshold)"
    )
    lines.append(
        f"Recommendation: {calibration.get('recommended_threshold', current.get('threshold', 65)):.0f} "
        f"— {html.escape(str(calibration.get('recommendation_reason', 'insufficient_feedback')).replace('_', ' '))}"
    )
    lines.append("Threshold changes are advisory only; v2 never changes them automatically.")
    return "\n".join(lines)[:3900]
