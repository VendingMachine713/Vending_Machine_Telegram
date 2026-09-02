import html
import json


def money(cents):
    if cents is None:
        return "not specified"
    return f"${int(cents) / 100:,.2f}"


def telegram_message_link(chat_id, message_id):
    value = str(chat_id or "")
    if value.startswith("-100") and len(value) > 4 and message_id:
        return f"https://t.me/c/{value[4:]}/{int(message_id)}"
    return None


def _short(value, limit=120):
    value = str(value or "")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def reason_summary(reasons_json, limit=5):
    try:
        reasons = json.loads(reasons_json or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    lines = []
    labels = {
        "category": "same category",
        "category_unknown": "category uncertain",
        "terms": "product terms overlap",
        "within_budget": "within WTB budget",
        "priced_supply": "supply has a price",
        "location": "location overlap",
        "location_mismatch": "different location hints",
        "freshness": "recent activity",
        "extraction_confidence": "listing confidence",
        "direct_sale": "direct sale listing",
    }
    for reason in reasons[:limit]:
        code = reason.get("code", "signal")
        points = reason.get("points")
        label = labels.get(code, code.replace("_", " "))
        detail = reason.get("detail")
        suffix = f" (+{float(points):.1f})" if isinstance(points, (int, float)) and points else ""
        if code == "terms" and isinstance(detail, list):
            label += ": " + ", ".join(str(x) for x in detail[:6])
        elif code == "location" and isinstance(detail, list):
            label += ": " + ", ".join(str(x) for x in detail[:4])
        lines.append(label + suffix)
    return lines


def format_match(row, *, include_reasons=True):
    demand_title = html.escape(_short(row["demand_title"] or "Wanted item", 110))
    supply_title = html.escape(_short(row["supply_title"] or "Available listing", 110))
    demand_chat = html.escape(_short(row["demand_chat_title"] or row["demand_chat_id"], 55))
    supply_chat = html.escape(_short(row["supply_chat_title"] or row["supply_chat_id"], 55))
    lines = [
        f"<b>Match #{row['id']} — {float(row['score']):.1f}/100</b>",
        f"Confidence: {float(row['confidence']):.0%} | Status: {html.escape(str(row['status']))}",
        "",
        f"<b>WTB:</b> {demand_title}",
        f"Budget: {html.escape(money(row['demand_budget']))} | {demand_chat}",
        f"<b>Supply:</b> {supply_title}",
        f"Price: {html.escape(money(row['supply_price']))} | {supply_chat}",
    ]
    demand_link = telegram_message_link(row["demand_chat_id"], row["demand_message_id"])
    supply_link = telegram_message_link(row["supply_chat_id"], row["supply_message_id"])
    links = []
    if demand_link:
        links.append(f'<a href="{html.escape(demand_link, quote=True)}">Open WTB</a>')
    if supply_link:
        links.append(f'<a href="{html.escape(supply_link, quote=True)}">Open supply</a>')
    if links:
        lines.append(" | ".join(links))
    if include_reasons:
        reasons = reason_summary(row["reasons_json"])
        if reasons:
            lines.append("")
            lines.append("<b>Why it matched</b>")
            lines.extend("• " + html.escape(reason) for reason in reasons)
    return "\n".join(lines)


def format_match_alert(row):
    return "🔎 <b>New marketplace match</b>\n\n" + format_match(row, include_reasons=True)
