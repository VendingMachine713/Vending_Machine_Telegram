from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import sqlite3

from .db import Database, utcnow

ACTIVE = {"pending", "retry", "deferred", "processing", "sending", "uncertain"}
MUTABLE_UNSENT = {"pending", "retry", "deferred"}
UNCERTAIN_OUTCOMES = {"uncertain", "send_timeout_uncertain", "uncertain_telegram_ack", "interrupted_send"}
SAFE_PRE_SEND_KINDS = {
    None, "", "slow_mode", "flood_wait", "worker_busy", "account_cooldown_or_pacing",
    "interrupted_processing", "deferred", "network_unavailable", "network_error",
    "media_forbidden", "text_forbidden", "compatible_content_missing",
}


def _provably_unsent(con, row) -> tuple[bool, str]:
    if row["status"] not in MUTABLE_UNSENT:
        return False, f"status={row['status']} is not safely suppressible"
    if row["telegram_message_ids"]:
        return False, "Telegram message IDs exist"
    attempts = con.execute(
        "SELECT outcome,error_kind,telegram_message_ids FROM delivery_attempts WHERE queue_id=? ORDER BY id",
        (row["id"],),
    ).fetchall()
    for a in attempts:
        outcome = str(a["outcome"] or "").lower()
        kind = str(a["error_kind"] or "").lower()
        if a["telegram_message_ids"]:
            return False, "delivery-attempt message IDs exist"
        if outcome == "sent" or outcome in UNCERTAIN_OUTCOMES or kind in UNCERTAIN_OUTCOMES:
            return False, f"delivery attempt is acknowledgement-ambiguous ({outcome or kind})"
    kind = row["error_kind"]
    if kind not in SAFE_PRE_SEND_KINDS and int(row["attempts"] or 0) > 0:
        return False, f"attempted row has non-pre-send error_kind={kind}"
    return True, "no send acknowledgement/evidence exists"


def queue_hygiene_plan(db: Database, *, campaign_id: str | None = None) -> dict:
    where = "WHERE status IN ('pending','retry','deferred','processing','sending','uncertain')"
    params: list[object] = []
    if campaign_id:
        where += " AND campaign_id=?"; params.append(campaign_id)
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(
            f"SELECT * FROM queue {where} ORDER BY group_id,id", params
        ).fetchall()]
        grouped: dict[int, list[dict]] = defaultdict(list)
        for r in rows:
            grouped[int(r["group_id"])].append(r)
        actions = []
        review = []
        healthy = 0
        for gid, group_rows in grouped.items():
            if len(group_rows) <= 1:
                healthy += 1; continue
            in_flight = [r for r in group_rows if r["status"] in {"processing", "sending"}]
            uncertain = [r for r in group_rows if r["status"] == "uncertain"]
            ordinary = [r for r in group_rows if r["status"] in MUTABLE_UNSENT]
            if in_flight:
                review.append({"group_id": gid, "reason": "in_flight_overlap", "jobs": [r["id"] for r in group_rows]})
                continue
            if uncertain:
                # UNCERTAIN is delivery evidence, not a disposable duplicate. Multiple
                # UNCERTAIN rows for one group can represent separate historical sends;
                # they MUST block the database uniqueness guard until reconciled.
                if len(uncertain) > 1:
                    review.append({
                        "group_id": gid,
                        "reason": "multiple_uncertain_delivery_evidence",
                        "jobs": [int(r["id"]) for r in uncertain],
                        "detail": "multiple UNCERTAIN rows require Telegram-history evidence; none were mutated",
                    })
                # Suppress only ordinary overlap rows that are provably pre-send.
                for r in ordinary:
                    safe, why = _provably_unsent(con, r)
                    if safe:
                        actions.append({"queue_id": int(r["id"]), "group_id": gid, "action": "cancel_duplicate_suppressed", "keeper_ids": [int(x["id"]) for x in uncertain], "reason": "UNCERTAIN delivery evidence takes precedence; " + why})
                    else:
                        review.append({"group_id": gid, "queue_id": int(r["id"]), "reason": "uncertain_overlap_not_provably_unsent", "detail": why})
                continue
            # No ambiguous evidence: keep the oldest unresolved obligation and
            # suppress only younger rows proven to be unsent.
            keeper = min(group_rows, key=lambda r: int(r["id"]))
            for r in group_rows:
                if r["id"] == keeper["id"]:
                    continue
                safe, why = _provably_unsent(con, r)
                if safe:
                    actions.append({"queue_id": int(r["id"]), "group_id": gid, "action": "cancel_duplicate_suppressed", "keeper_ids": [int(keeper["id"])], "reason": "older unresolved obligation retained; " + why})
                else:
                    review.append({"group_id": gid, "queue_id": int(r["id"]), "reason": "overlap_not_provably_unsent", "detail": why})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "campaign_id": campaign_id,
        "active_rows": len(rows),
        "active_groups": len(grouped),
        "healthy_singletons": healthy,
        "safe_suppressions": len(actions),
        "review_count": len(review),
        "actions": actions,
        "review": review,
        "uncertain_mutated": False,
    }


def apply_queue_hygiene(db: Database, *, campaign_id: str | None = None, actor: str = "v5_queue_hygiene") -> dict:
    plan = queue_hygiene_plan(db, campaign_id=campaign_id)
    applied = []
    now = utcnow()
    with db.connect() as con:
        for action in plan["actions"]:
            qid = int(action["queue_id"])
            row = con.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone()
            if not row:
                continue
            safe, why = _provably_unsent(con, row)
            if not safe:
                continue
            changed = con.execute(
                """UPDATE queue SET status='cancelled',error_kind='duplicate_suppressed',
                   last_error=?,resolved_at=?,phase='cancelled',phase_percent=100,
                   phase_detail='V5 safe queue hygiene suppressed redundant unsent obligation',
                   phase_updated_at=?,updated_at=?
                   WHERE id=? AND status IN ('pending','retry','deferred')""",
                (action["reason"][:1000], now, now, now, qid),
            )
            if changed.rowcount:
                con.execute(
                    "INSERT INTO audit_log(created_at,actor,action,target_type,target_id,details) VALUES(?,?,?,?,?,?)",
                    (now, actor, "duplicate_suppressed", "queue_job", str(qid), action["reason"][:1000]),
                )
                applied.append(qid)
    result = queue_hygiene_plan(db, campaign_id=campaign_id)
    result.update({"applied": len(applied), "applied_ids": applied, "initial_safe_suppressions": plan["safe_suppressions"]})
    return result


def active_group_conflicts(db: Database) -> list[dict]:
    """Return unresolved group conflicts without mutating delivery evidence."""
    with db.connect() as con:
        rows = con.execute(
            """SELECT group_id, COUNT(*) AS active_count,
                      GROUP_CONCAT(id) AS queue_ids,
                      GROUP_CONCAT(status) AS statuses
               FROM queue
               WHERE status IN ('pending','retry','deferred','processing','sending','uncertain')
               GROUP BY group_id HAVING COUNT(*) > 1
               ORDER BY group_id"""
        ).fetchall()
    return [
        {
            "group_id": int(r["group_id"]),
            "active_count": int(r["active_count"]),
            "queue_ids": [int(x) for x in str(r["queue_ids"] or "").split(",") if x],
            "statuses": [x for x in str(r["statuses"] or "").split(",") if x],
        }
        for r in rows
    ]


def install_active_group_guard(db: Database) -> dict:
    """Install the DB anti-spam invariant only when the live queue can support it.

    Historical UNCERTAIN/ambiguous overlap is evidence and can legitimately prevent
    a UNIQUE index from being installed. That is a degraded safety mode, not an
    upgrade failure: application-level admission/worker guards remain active.
    """
    plan = queue_hygiene_plan(db)
    conflicts = active_group_conflicts(db)
    if plan["safe_suppressions"] or plan["review_count"] or conflicts:
        return {
            "installed": False,
            "reason": "unresolved_overlap",
            "degraded_safe_mode": True,
            "application_guards_active": True,
            "conflicts": conflicts,
            "plan": plan,
        }
    try:
        with db.connect() as con:
            con.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_queue_one_unresolved_per_group
                           ON queue(group_id)
                           WHERE status IN ('pending','retry','deferred','processing','sending','uncertain')""")
    except sqlite3.IntegrityError as exc:
        # Race-safe fail-closed behaviour: never mutate evidence merely to force the
        # index into existence. Report degraded application-level protection instead.
        return {
            "installed": False,
            "reason": "unique_conflict_detected",
            "degraded_safe_mode": True,
            "application_guards_active": True,
            "error": str(exc),
            "conflicts": active_group_conflicts(db),
        }
    return {"installed": True, "reason": None, "degraded_safe_mode": False, "application_guards_active": True, "conflicts": []}
