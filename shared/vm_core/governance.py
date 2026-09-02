from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import PlatformDB, utcnow
from .paths import project_root


TERMINAL_STATUSES = {"DISMISSED", "COMPLETED", "EXPIRED"}
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "PROPOSED": {"ACCEPTED", "DISMISSED"},
    "BLOCKED": {"DISMISSED"},
    "ACCEPTED": {"COMPLETED", "DISMISSED"},
    "DISMISSED": set(),
    "COMPLETED": set(),
    "EXPIRED": set(),
}


class RecommendationGovernanceError(RuntimeError):
    """Raised when a recommendation governance operation is invalid."""


@dataclass(frozen=True)
class RecommendationDecision:
    recommendation_key: str
    previous_status: str
    status: str
    actor: str
    event_id: int


def _recommendation_by_key(db: PlatformDB, recommendation_key: str) -> dict[str, Any]:
    with db.connect() as con:
        row = con.execute(
            "SELECT * FROM intelligence_recommendations WHERE recommendation_key=?",
            (recommendation_key,),
        ).fetchone()
    if row is None:
        raise RecommendationGovernanceError(f"recommendation not found: {recommendation_key}")
    return dict(row)


def transition_recommendation(
    recommendation_key: str,
    target_status: str,
    *,
    actor: str = "operator",
    note: str | None = None,
    root: Path | None = None,
) -> RecommendationDecision:
    """Apply one governed recommendation state transition and record an audit event.

    This changes VM Intelligence metadata only. It never performs Telegram actions,
    retries campaign jobs, sends messages, or mutates bot-owned databases.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()

    target = target_status.upper().strip()
    actor = actor.strip() or "operator"
    row = _recommendation_by_key(db, recommendation_key)
    current = str(row["status"]).upper()

    if target == current:
        raise RecommendationGovernanceError(
            f"recommendation {recommendation_key} is already {current}"
        )
    allowed = ALLOWED_TRANSITIONS.get(current)
    if allowed is None:
        raise RecommendationGovernanceError(f"unknown current recommendation status: {current}")
    if target not in allowed:
        permitted = ", ".join(sorted(allowed)) or "none"
        raise RecommendationGovernanceError(
            f"invalid transition {current} -> {target}; allowed: {permitted}"
        )

    now = utcnow()
    with db.connect() as con:
        cur = con.execute(
            "UPDATE intelligence_recommendations "
            "SET status=?, updated_at_utc=? "
            "WHERE recommendation_key=? AND status=?",
            (target, now, recommendation_key, current),
        )
        if cur.rowcount != 1:
            raise RecommendationGovernanceError(
                "recommendation changed concurrently; refresh and retry"
            )

    event_id = db.add_event(
        f"recommendation.{target.lower()}",
        "vm_core.governance",
        {
            "recommendation_key": recommendation_key,
            "recommendation_type": row["recommendation_type"],
            "previous_status": current,
            "status": target,
            "actor": actor,
            "note": (note or "")[:1000],
            "automatic_execution": False,
        },
        severity="INFO",
        subject_type=row.get("subject_type"),
        subject_id=row.get("subject_id"),
        correlation_id=f"recommendation:{row['id']}",
        evidence={
            "recommendation_id": row["id"],
            "rule_id": row["rule_id"],
            "rule_version": row["rule_version"],
        },
    )
    return RecommendationDecision(
        recommendation_key=recommendation_key,
        previous_status=current,
        status=target,
        actor=actor,
        event_id=event_id,
    )


def recommendation_history(
    recommendation_key: str,
    *,
    root: Path | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return audit events associated with one recommendation."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    row = _recommendation_by_key(db, recommendation_key)
    correlation_id = f"recommendation:{row['id']}"
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM events WHERE correlation_id=? ORDER BY id DESC LIMIT ?",
            (correlation_id, max(1, int(limit))),
        ).fetchall()
    return [dict(item) for item in rows]


def governance_summary(root: Path | None = None) -> dict[str, Any]:
    """Return compact recommendation governance state for passive/admin views."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    rows = db.recommendations(500)
    counts: dict[str, int] = {status: 0 for status in ALLOWED_TRANSITIONS}
    for row in rows:
        status = str(row.get("status") or "").upper()
        counts[status] = counts.get(status, 0) + 1
    actionable = [
        row for row in rows
        if str(row.get("status") or "").upper() in {"PROPOSED", "ACCEPTED"}
    ]
    return {
        "counts": counts,
        "actionable": actionable,
        "automatic_execution": False,
    }
