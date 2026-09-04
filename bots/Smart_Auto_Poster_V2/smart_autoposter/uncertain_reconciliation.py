from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .delivery_ledger import attempts_for_job


def _dt(value: str | None) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(timezone.utc)
    d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _norm(text: str | None) -> str:
    value = unicodedata.normalize("NFC", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in value.strip().split("\n"))


def _ids(value: Any) -> list[int]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if not isinstance(value, (list, tuple)):
        value = [value]
    out = []
    for x in value:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return list(dict.fromkeys(out))


@dataclass(frozen=True)
class ReconciliationResult:
    job_id: int
    group_id: int
    group_name: str
    campaign_id: str
    classification: str
    confidence: str
    account_key: str | None
    evidence: str
    matched_message_ids: list[int]
    candidate_count: int
    safe_to_mark_sent: bool
    safe_to_retry: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_history_evidence(
    *,
    job: dict[str, Any],
    messages: list[dict[str, Any]],
    expected_media_count: int,
    direct_message_ids: list[int] | None = None,
) -> ReconciliationResult:
    caption = _norm(job.get("caption"))
    mode = str(job.get("mode") or "text").lower()
    direct = set(_ids(direct_message_ids))

    def result(kind: str, confidence: str, evidence: str, matches: list[dict[str, Any]], safe: bool) -> ReconciliationResult:
        account = None
        accounts = {str(m.get("account_key")) for m in matches if m.get("account_key")}
        if len(accounts) == 1:
            account = next(iter(accounts))
        return ReconciliationResult(
            job_id=int(job["id"]),
            group_id=int(job["group_id"]),
            group_name=str(job.get("group_name") or job["group_id"]),
            campaign_id=str(job.get("campaign_id") or ""),
            classification=kind,
            confidence=confidence,
            account_key=account,
            evidence=evidence,
            matched_message_ids=sorted({int(m["id"]) for m in matches if m.get("id") is not None}),
            candidate_count=len(matches),
            safe_to_mark_sent=safe,
            safe_to_retry=False,
        )

    outgoing = [m for m in messages if bool(m.get("out"))]

    if direct:
        matched = [m for m in outgoing if int(m.get("id") or -1) in direct]
        if direct.issubset({int(m.get("id")) for m in matched if m.get("id") is not None}):
            if caption and not any(_norm(m.get("text")) == caption for m in matched):
                return result("DIRECT_ID_CONTENT_MISMATCH", "LOW",
                              "Stored Telegram message IDs exist but the visible message text does not match this job.",
                              matched, False)
            return result("PROVEN_SENT_BY_ID", "HIGH",
                          "Stored Telegram message IDs were found in the destination history as outgoing messages.",
                          matched, True)

    if not caption:
        return result("INSUFFICIENT_PAYLOAD_FINGERPRINT", "LOW",
                      "No caption is available and there are no stored Telegram message IDs; history-only proof would be unsafe.",
                      [], False)

    exact = [m for m in outgoing if _norm(m.get("text")) == caption]
    if not exact:
        return result("NO_MATCH", "LOW",
                      "No outgoing message with the exact normalized caption was found inside the bounded history window.",
                      [], False)

    # Collapse album members to a single evidence candidate by grouped_id. A caption
    # usually appears on one album member while all members share grouped_id.
    candidates: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for m in exact:
        gid = m.get("grouped_id")
        key = f"g:{gid}" if gid is not None else f"m:{m.get('id')}"
        if key in seen_groups:
            continue
        seen_groups.add(key)
        row = dict(m)
        if gid is not None:
            members = [x for x in outgoing if x.get("grouped_id") == gid]
            row["_album_members"] = members
        candidates.append(row)

    if len(candidates) > 1:
        return result("AMBIGUOUS_MULTIPLE_MATCHES", "MEDIUM",
                      "More than one outgoing message/album with the exact caption exists inside the history window.",
                      candidates, False)

    match = candidates[0]
    if mode == "photo":
        members = match.get("_album_members") or [match]
        media_members = [x for x in members if bool(x.get("has_media"))]
        if expected_media_count > 0 and len(media_members) != expected_media_count:
            return result("MEDIA_COUNT_MISMATCH", "MEDIUM",
                          f"Exact caption matched, but Telegram history shows {len(media_members)} media item(s); expected {expected_media_count}.",
                          members, False)
        return result("PROVEN_SENT_BY_ALBUM", "HIGH",
                      f"Exactly one outgoing album matched the exact caption and expected media count ({expected_media_count}).",
                      members, True)

    return result("PROVEN_SENT_BY_TEXT", "HIGH",
                  "Exactly one outgoing text message matched the exact normalized caption inside the bounded send window.",
                  [match], True)


def uncertain_jobs(db, limit: int = 100) -> list[dict[str, Any]]:
    with db.connect() as con:
        rows = con.execute(
            """SELECT q.*,d.group_name,d.mode,d.topic_id,d.primary_access,d.secondary_access,
                      c.caption,c.media_json
               FROM queue q
               JOIN destinations d ON d.group_id=q.group_id
               JOIN content c ON c.content_id=COALESCE(q.content_id,(
                   SELECT content_id FROM campaigns WHERE campaign_id=q.campaign_id
               ))
               WHERE q.status='uncertain'
               ORDER BY q.updated_at ASC,q.id ASC
               LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [dict(r) for r in rows]


def candidate_accounts(job: dict[str, Any], attempts: list[dict[str, Any]], auth: dict[str, dict]) -> list[str]:
    out: list[str] = []
    for attempt in reversed(attempts):
        key = str(attempt.get("account_key") or "")
        if key in {"primary", "secondary"} and key not in out:
            out.append(key)
    key = str(job.get("account_key") or "")
    if key in {"primary", "secondary"} and key not in out:
        out.append(key)
    for key in ("primary", "secondary"):
        if key in out:
            continue
        if not bool(job.get(f"{key}_access")):
            continue
        if auth.get(key, {}).get("authorized"):
            out.append(key)
    return [x for x in out if auth.get(x, {}).get("authorized")]


async def audit_uncertain_deliveries(
    db,
    pool,
    *,
    limit: int = 100,
    before_seconds: int = 120,
    after_seconds: int = 900,
    history_limit: int = 300,
) -> dict[str, Any]:
    auth = await pool.authorization()
    jobs = uncertain_jobs(db, limit)
    results: list[ReconciliationResult] = []

    for job in jobs:
        attempts = attempts_for_job(db, int(job["id"]))
        latest = attempts[-1] if attempts else {}
        direct = _ids(job.get("telegram_message_ids")) or _ids(latest.get("telegram_message_ids"))
        anchor = _dt(latest.get("started_at") or job.get("updated_at") or job.get("created_at"))
        start = anchor - timedelta(seconds=max(0, int(before_seconds)))
        end = anchor + timedelta(seconds=max(30, int(after_seconds)))
        accounts = candidate_accounts(job, attempts, auth)

        if not accounts:
            results.append(ReconciliationResult(
                int(job["id"]), int(job["group_id"]), str(job["group_name"]), str(job["campaign_id"]),
                "NO_AUTHORIZED_EVIDENCE_ACCOUNT", "LOW", None,
                "No authorized account that can safely inspect the destination is available.",
                [], 0, False, False,
            ))
            continue

        observed: list[dict[str, Any]] = []
        errors: list[str] = []
        for account in accounts:
            try:
                if direct:
                    rows = await pool.message_evidence_by_ids(account, int(job["group_id"]), direct)
                else:
                    rows = await pool.history_window(
                        account, int(job["group_id"]), start, end,
                        limit=max(20, int(history_limit)),
                    )
                observed.extend(rows)
            except Exception as exc:
                errors.append(f"{account}:{type(exc).__name__}")

        if not observed and errors:
            results.append(ReconciliationResult(
                int(job["id"]), int(job["group_id"]), str(job["group_name"]), str(job["campaign_id"]),
                "HISTORY_LOOKUP_ERROR", "LOW", None,
                "Telegram history lookup failed on available evidence account(s): " + ", ".join(errors),
                [], 0, False, False,
            ))
            continue

        try:
            expected_media_count = len(json.loads(job.get("media_json") or "[]"))
        except Exception:
            expected_media_count = 0
        classified = classify_history_evidence(
            job=job,
            messages=observed,
            expected_media_count=expected_media_count,
            direct_message_ids=direct,
        )
        results.append(classified)

    counts: dict[str, int] = {}
    for r in results:
        counts[r.classification] = counts.get(r.classification, 0) + 1
    proven = sum(1 for r in results if r.safe_to_mark_sent)
    return {
        "mode": "READ_ONLY",
        "uncertain_jobs": len(jobs),
        "proven_sent": proven,
        "still_unresolved": len(results) - proven,
        "classifications": counts,
        "results": [r.to_dict() for r in results],
        "safety": {
            "queue_mutations": False,
            "telegram_sends": False,
            "automatic_retries": False,
            "absence_of_history_never_proves_safe_retry": True,
        },
    }


def format_reconciliation_report(report: dict[str, Any]) -> str:
    lines = [
        "=" * 100,
        " SMART AUTO POSTER - UNCERTAIN DELIVERY RECONCILIATION",
        "=" * 100,
        f"Mode: READ-ONLY | uncertain={report['uncertain_jobs']} | proven_sent={report['proven_sent']} | unresolved={report['still_unresolved']}",
        "",
    ]
    for row in report["results"]:
        mark = "PROVEN" if row["safe_to_mark_sent"] else "REVIEW"
        lines.append(
            f"#{row['job_id']:<5} {mark:<6} {row['classification']:<30} {row['group_name']}"
        )
        lines.append(
            f"       confidence={row['confidence']} account={row.get('account_key') or '-'} ids={row['matched_message_ids'] or '-'}"
        )
        lines.append(f"       {row['evidence']}")
    lines += [
        "",
        "Safety: no queue rows changed, no Telegram messages sent, and NO_MATCH never becomes an automatic retry.",
    ]
    return "\n".join(lines)
