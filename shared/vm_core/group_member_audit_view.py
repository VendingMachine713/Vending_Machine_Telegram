from __future__ import annotations

from typing import Any


def _short(value: Any) -> str:
    text = str(value or "")
    if len(text) <= 18:
        return text
    parts = text.split(":")
    if len(parts) == 3:
        return f"{parts[0]}:{parts[1]}:…{parts[2][-8:]}"
    return f"…{text[-12:]}"


def _count(group: dict[str, Any], key: str) -> int:
    try:
        return int(group.get("summary_cards", {}).get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def render_group_member_audit(summary: dict[str, Any]) -> str:
    """Render a compact terminal version of the Mission Control audit screen."""
    lines = [
        "=" * 78,
        " MISSION CONTROL > GROUP MEMBER AUDIT",
        "=" * 78,
        f"STATUS: {summary.get('status', 'UNKNOWN')}",
        f"Audited groups: {summary.get('group_count', 0)} | "
        f"Audited members: {summary.get('audited_member_count', 0)} | "
        f"Attention groups: {summary.get('attention_group_count', 0)}",
        "",
    ]
    groups = summary.get("groups") or []
    if not groups:
        lines.extend([
            "No group-member audit evidence is available yet.",
            "",
            "This view is read-only. It does not enumerate members or send messages.",
        ])
        return "\n".join(lines)

    group = groups[0]
    lines.extend([
        f"GROUP: {_short(group.get('group_subject_id'))}",
        f"Last audit: {group.get('latest_audit_utc') or 'UNKNOWN'} | "
        f"Coverage: {group.get('coverage_percent') if group.get('coverage_percent') is not None else 'UNKNOWN'} | "
        f"Freshness: {group.get('data_freshness', 'UNKNOWN')}",
        "",
        "SUMMARY CARDS",
        f"[ Members {_count(group, 'members')} ] "
        f"[ Likely human {_count(group, 'likely_human')} ] "
        f"[ Bots {_count(group, 'bot_accounts')} ]",
        f"[ Deleted {_count(group, 'deleted')} ] "
        f"[ Uncertain {_count(group, 'uncertain')} ] "
        f"[ Known {_count(group, 'known_contacts')} ] "
        f"[ Restricted {_count(group, 'restricted')} ]",
        "",
        "ATTENTION REQUIRED",
    ])
    attention = group.get("attention") or []
    if attention:
        for item in attention:
            count = item.get("count")
            suffix = f" ({count})" if count is not None else ""
            lines.append(f"- {item.get('severity', 'INFO')}: {item.get('code', 'UNKNOWN')}{suffix}")
    else:
        lines.append("- Nothing in this group currently requires operator review.")

    filters = summary.get("filters", {})
    lines.extend([
        "",
        "FILTERS",
        f"- Categories: {', '.join(filters.get('categories', []))}",
        f"- Confidence: {', '.join(filters.get('confidence_labels', []))}",
        "- Known contact: yes / no",
        "- Review required: yes / no",
        "- Activity state: recent / active / inactive / unknown",
        "",
        "MEMBER TABLE",
        f"{'MEMBER':<26} {'CATEGORY':<18} {'CONFIDENCE':<22} {'KNOWN':<7} {'REVIEW':<7}",
        "-" * 78,
    ])
    members = group.get("members") or []
    for member in members[:20]:
        lines.append(
            f"{_short(member.get('member_subject_id')):<26} "
            f"{str(member.get('classification', 'UNCERTAIN')):<18} "
            f"{str(member.get('confidence_label', 'UNKNOWN')):<22} "
            f"{('YES' if member.get('known_contact') else 'NO'):<7} "
            f"{('YES' if member.get('review_required') else 'NO'):<7}"
        )

    lines.extend(["", "DETAIL PANEL"])
    if members:
        member = members[0]
        lines.extend([
            f"- Member: {_short(member.get('member_subject_id'))}",
            f"- Classification: {member.get('classification')}",
            f"- Confidence: {member.get('confidence_label')}",
            f"- Reasons: {', '.join(member.get('reason_codes') or []) or 'NONE'}",
            f"- Activity: {member.get('activity_state')}",
            f"- Mutual groups: {member.get('mutual_group_count')}",
            f"- Known contact: {'YES' if member.get('known_contact') else 'NO'}",
            f"- Review required: {'YES' if member.get('review_required') else 'NO'}",
            f"- Evidence time: {member.get('evidence_created_at_utc')}",
        ])
    else:
        lines.append("- No member rows available.")

    lines.extend(["", "AUDIT HISTORY"])
    history = group.get("audit_history") or []
    if history:
        for row in history[:5]:
            counts = row.get("classification_counts") or {}
            lines.append(
                f"- {row.get('created_at_utc')} | visible={row.get('visible_member_count')} "
                f"coverage={row.get('coverage_percent')} | "
                f"human={counts.get('LIKELY_HUMAN', 0)} bots={counts.get('BOT_ACCOUNT', 0)} "
                f"uncertain={counts.get('UNCERTAIN', 0)} deleted={counts.get('DELETED', 0)}"
            )
    else:
        lines.append("- No snapshot history available.")

    lines.extend([
        "",
        "OPERATOR ACTIONS",
        "- View evidence / mark manual review / add note / open relationship profile",
        "- Export filtered results / add to approved outreach shortlist",
        "- Bulk messaging is NOT available from this audit view.",
        "",
        "SAFETY",
        f"- Read only: {'YES' if summary.get('read_only') else 'NO'}",
        f"- Automatic outreach: {'ON' if summary.get('automatic_outreach') else 'OFF'}",
        f"- Automatic execution: {'ON' if summary.get('automatic_execution') else 'OFF'}",
        f"- External action authority: {'ON' if summary.get('external_action_authority') else 'OFF'}",
    ])
    return "\n".join(lines)
