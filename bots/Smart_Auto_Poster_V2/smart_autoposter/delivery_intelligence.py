from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import Database, utcnow


UNCERTAIN_KINDS = {"uncertain_telegram_ack", "send_timeout_uncertain", "interrupted_send"}
TIMING_KINDS = {"slow_mode", "flood_wait", "worker_busy", "deferred", "account_cooldown_or_pacing"}
ACCOUNT_KINDS = {"auth_session", "no_authorized_account", "account_disabled", "account_cooldown"}
TRANSIENT_KINDS = {"network", "worker_busy", "FloodWaitError", "SlowModeWaitError"}
PERMANENT_KINDS = {
    "ChatWriteForbiddenError", "ChatSendMediaForbiddenError", "ChatSendPhotosForbiddenError",
    "ChatSendPlainForbiddenError", "UserBannedInChannelError", "ChannelPrivateError",
    "ChatAdminRequiredError", "PeerIdInvalidError", "TopicDeletedError", "MessageIdInvalidError",
    "invalid_topic", "invalid_media", "quiet_hours_invalid",
}


def failure_family(kind: str | None, status: str | None = None) -> str:
    kind = (kind or "unknown").strip()
    if status == "uncertain" or kind in UNCERTAIN_KINDS:
        return "uncertain"
    if kind in TIMING_KINDS:
        return "timing"
    if kind in ACCOUNT_KINDS:
        return "account"
    if kind in PERMANENT_KINDS:
        return "permanent_destination"
    if kind in TRANSIENT_KINDS:
        return "transient"
    if status in {"failed", "quarantined"}:
        return "terminal_other"
    return "retry_other"


def _recommended_action(family: str) -> str:
    return {
        "uncertain": "reconcile Telegram history before any retry",
        "timing": "wait for the recorded eligibility time",
        "account": "repair or fail over the affected Telegram account",
        "permanent_destination": "disable and review destination access/capabilities",
        "transient": "retry with bounded backoff",
        "terminal_other": "inspect terminal error before manual recovery",
        "retry_other": "retry with bounded backoff and observe classification",
    }[family]


def delivery_diagnosis(db: Database, *, hours: int = 168, campaign_id: str | None = None) -> dict[str, Any]:
    hours = max(1, int(hours))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    params: list[Any] = [cutoff]
    campaign_sql = ""
    if campaign_id:
        campaign_sql = " AND q.campaign_id=?"
        params.append(campaign_id)
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(
            f'''SELECT q.id,q.run_key,q.campaign_id,q.group_id,d.group_name,q.account_key,q.status,
                       q.attempts,q.max_attempts,q.error_kind,q.last_error,q.due_at,q.updated_at
                FROM queue q JOIN destinations d ON d.group_id=q.group_id
                WHERE q.updated_at>=? {campaign_sql}
                  AND q.status IN ('retry','deferred','failed','quarantined','uncertain')
                ORDER BY q.updated_at DESC,q.id DESC''', params).fetchall()
        ]
        attempt_counts = [dict(r) for r in con.execute(
            f'''SELECT COALESCE(error_kind,'success') error_kind,outcome,COUNT(*) n
                FROM delivery_attempts da
                WHERE da.created_at>=? {campaign_sql.replace('q.campaign_id','da.campaign_id')}
                GROUP BY COALESCE(error_kind,'success'),outcome ORDER BY n DESC''', params).fetchall()
        ]

    families: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    destinations: dict[int, dict[str, Any]] = {}
    for row in rows:
        family = failure_family(row.get("error_kind"), row.get("status"))
        row["failure_family"] = family
        row["recommended_action"] = _recommended_action(family)
        families[family] += 1
        kinds[row.get("error_kind") or "unknown"] += 1
        gid = int(row["group_id"])
        item = destinations.setdefault(gid, {"group_id": gid, "group_name": row["group_name"], "jobs": 0, "families": Counter(), "kinds": Counter()})
        item["jobs"] += 1
        item["families"][family] += 1
        item["kinds"][row.get("error_kind") or "unknown"] += 1

    destination_list = []
    for item in destinations.values():
        item["families"] = dict(item["families"].most_common())
        item["kinds"] = dict(item["kinds"].most_common())
        destination_list.append(item)
    destination_list.sort(key=lambda x: (-x["jobs"], x["group_name"].casefold()))

    return {
        "generated_at": utcnow(),
        "window_hours": hours,
        "campaign_id": campaign_id,
        "problem_jobs": len(rows),
        "families": dict(families.most_common()),
        "error_kinds": dict(kinds.most_common()),
        "attempt_outcomes": attempt_counts,
        "destinations": destination_list,
        "jobs": rows,
        "safety": {"uncertain_auto_retry": False, "mutated": False},
    }


def safe_recovery_plan(db: Database, *, campaign_id: str | None = None, apply: bool = False) -> dict[str, Any]:
    params: list[Any] = []
    campaign_sql = ""
    if campaign_id:
        campaign_sql = " AND campaign_id=?"
        params.append(campaign_id)
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(
            f'''SELECT id,campaign_id,group_id,status,attempts,max_attempts,error_kind
                FROM queue WHERE status IN ('retry','failed','quarantined','uncertain') {campaign_sql}
                ORDER BY id''', params).fetchall()]

        actions = []
        for row in rows:
            family = failure_family(row.get("error_kind"), row.get("status"))
            if family == "uncertain":
                action = "hold_for_history_reconciliation"
            elif row["status"] == "retry" and family == "permanent_destination":
                action = "close_impossible_retry"
            elif row["status"] == "retry" and int(row["attempts"] or 0) >= int(row["max_attempts"] or 4):
                action = "close_exhausted_retry"
            else:
                action = "leave_worker_managed"
            actions.append({**row, "failure_family": family, "action": action})

        changed = 0
        if apply:
            now = utcnow()
            ids = [x["id"] for x in actions if x["action"] in {"close_impossible_retry", "close_exhausted_retry"}]
            for job_id in ids:
                changed += con.execute(
                    "UPDATE queue SET status='failed',resolved_at=?,updated_at=? WHERE id=? AND status='retry'",
                    (now, now, job_id),
                ).rowcount
    if apply and changed:
        db.audit("delivery-intelligence", "safe_recovery_apply", target_type="queue", target_id=campaign_id or "all", details=f"closed_retries={changed}")
    return {
        "generated_at": utcnow(), "campaign_id": campaign_id, "apply": bool(apply),
        "changed": changed, "actions": actions,
        "uncertain_preserved": sum(1 for x in actions if x["action"] == "hold_for_history_reconciliation"),
    }
