from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import Database
from .reconciliation import CONFIRM_SENT, reconcile_uncertain


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    v = str(value).replace('Z', '+00:00')
    d = datetime.fromisoformat(v)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _norm(text: str | None) -> str:
    return ' '.join(str(text or '').replace('\r', '\n').split()).strip()


@dataclass
class EvidenceMatch:
    queue_id: int
    account_key: str | None
    group_id: int
    group_name: str
    expected_mode: str
    expected_media_count: int
    attempt_at: str
    window_start: str
    window_end: str
    candidate_count: int = 0
    exact_match_count: int = 0
    confidence: str = 'none'
    matched_message_ids: list[int] | None = None
    matched_grouped_id: int | None = None
    matched_at: str | None = None
    reason: str = 'no matching Telegram history found'
    account_source: str | None = None
    diagnostic_candidate_count: int = 0
    diagnostic_exact_count: int = 0
    diagnostic_nearest_seconds: int | None = None
    diagnostic_reason: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d['matched_message_ids'] = list(self.matched_message_ids or [])
        return d


def uncertain_evidence_jobs(db: Database, *, campaign_id: str | None = None, limit: int = 100) -> list[dict]:
    where = "WHERE q.status='uncertain'"
    params: list[Any] = []
    if campaign_id:
        where += " AND q.campaign_id=?"
        params.append(campaign_id)
    params.append(max(1, min(500, int(limit))))
    with db.connect() as con:
        rows = con.execute(
            f"""SELECT q.id,q.run_key,q.campaign_id,q.group_id,d.group_name,q.content_id,q.account_key,
                       q.error_kind,q.updated_at,q.telegram_message_ids,d.mode,
                       c.caption,c.media_json,
                       COALESCE((SELECT da.created_at FROM delivery_attempts da
                                 WHERE da.queue_id=q.id AND da.outcome IN ('uncertain','failed')
                                 ORDER BY da.id DESC LIMIT 1),q.updated_at) AS attempt_at,
                       (SELECT da.account_key FROM delivery_attempts da
                        WHERE da.queue_id=q.id AND da.account_key IS NOT NULL AND da.account_key<>''
                        ORDER BY da.id DESC LIMIT 1) AS attempt_account_key,
                       (SELECT qph.account_key FROM queue_phase_history qph
                        WHERE qph.queue_id=q.id AND qph.account_key IS NOT NULL AND qph.account_key<>''
                        ORDER BY qph.id DESC LIMIT 1) AS phase_account_key
                FROM queue q
                JOIN destinations d ON d.group_id=q.group_id
                LEFT JOIN content c ON c.content_id=q.content_id
                {where}
                ORDER BY attempt_at,q.id LIMIT ?""",
            params,
        ).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        try:
            d['expected_media_count'] = len(json.loads(d.get('media_json') or '[]'))
        except Exception:
            d['expected_media_count'] = 0
        d['inferred_account_key'] = d.get('account_key') or d.get('attempt_account_key') or d.get('phase_account_key')
        out.append(d)
    return out


def _message_text(msg) -> str:
    return _norm(getattr(msg, 'message', None) or getattr(msg, 'text', None) or '')


def _message_date(msg) -> datetime:
    d = getattr(msg, 'date', None)
    if d is None:
        return datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def evaluate_messages(job: dict, messages: list[Any], *, window_minutes: int = 15) -> EvidenceMatch:
    attempt = _dt(job.get('attempt_at'))
    start = attempt - timedelta(minutes=max(1, int(window_minutes)))
    end = attempt + timedelta(minutes=max(1, int(window_minutes)))
    expected_caption = _norm(job.get('caption'))
    expected_media = int(job.get('expected_media_count') or 0)
    mode = str(job.get('mode') or ('photo' if expected_media else 'text'))
    result = EvidenceMatch(
        queue_id=int(job['id']), account_key=job.get('account_key'), group_id=int(job['group_id']),
        group_name=str(job.get('group_name') or job['group_id']), expected_mode=mode,
        expected_media_count=expected_media, attempt_at=attempt.isoformat(timespec='seconds'),
        window_start=start.isoformat(timespec='seconds'), window_end=end.isoformat(timespec='seconds'),
    )
    outgoing = [m for m in messages if bool(getattr(m, 'out', False)) and start <= _message_date(m) <= end]
    result.candidate_count = len(outgoing)
    exact_groups: list[tuple[list[Any], int | None]] = []
    if expected_media > 0:
        grouped: dict[int, list[Any]] = {}
        for m in outgoing:
            gid = getattr(m, 'grouped_id', None)
            if gid is not None:
                grouped.setdefault(int(gid), []).append(m)
        for gid, group in grouped.items():
            texts = [_message_text(m) for m in group if _message_text(m)]
            caption_ok = expected_caption and expected_caption in texts
            media_count = sum(1 for m in group if getattr(m, 'media', None) is not None)
            if caption_ok and media_count == expected_media:
                exact_groups.append((group, gid))
    else:
        for m in outgoing:
            if expected_caption and _message_text(m) == expected_caption:
                exact_groups.append(([m], getattr(m, 'grouped_id', None)))
    result.exact_match_count = len(exact_groups)
    if len(exact_groups) == 1:
        group, grouped_id = exact_groups[0]
        ids = sorted(int(getattr(m, 'id')) for m in group if getattr(m, 'id', None) is not None)
        result.confidence = 'high'
        result.matched_message_ids = ids
        result.matched_grouped_id = int(grouped_id) if grouped_id is not None else None
        result.matched_at = min(_message_date(m) for m in group).isoformat(timespec='seconds')
        result.reason = 'unique exact outgoing Telegram history match'
    elif len(exact_groups) > 1:
        result.confidence = 'ambiguous'
        result.reason = f'{len(exact_groups)} exact matches found in evidence window; automatic reconciliation blocked'
    elif outgoing:
        result.confidence = 'none'
        result.reason = 'outgoing Telegram history exists in window but no unique exact payload match'
    return result


def _nearest_seconds(attempt: datetime, messages: list[Any]) -> int | None:
    if not messages:
        return None
    return min(abs(int((_message_date(m) - attempt).total_seconds())) for m in messages)


def evaluate_diagnostic_messages(job: dict, messages: list[Any], *, window_minutes: int = 120) -> dict:
    """Broader read-only context. Never provides automatic reconciliation authority."""
    attempt = _dt(job.get('attempt_at'))
    start = attempt - timedelta(minutes=max(1, int(window_minutes)))
    end = attempt + timedelta(minutes=max(1, int(window_minutes)))
    outgoing = [m for m in messages if bool(getattr(m, 'out', False)) and start <= _message_date(m) <= end]
    strict_like = evaluate_messages(job, outgoing, window_minutes=window_minutes)
    return {
        'candidate_count': len(outgoing),
        'exact_match_count': int(strict_like.exact_match_count),
        'nearest_seconds': _nearest_seconds(attempt, outgoing),
        'reason': ('broader-window exact candidate(s) found; HUMAN REVIEW ONLY'
                   if strict_like.exact_match_count else
                   ('nearby outgoing history exists but payload does not exactly match' if outgoing else
                    'no outgoing Telegram history found in broader diagnostic window')),
    }


async def _history_window(client, entity, *, start: datetime, end: datetime, limit: int = 600) -> list[Any]:
    history = []
    async for msg in client.iter_messages(entity, limit=max(1, int(limit)), offset_date=end):
        d = _message_date(msg)
        if d < start:
            break
        if d <= end:
            history.append(msg)
    return history


async def scan_uncertain_history(db: Database, settings, *, campaign_id: str | None = None,
                                 window_minutes: int = 20, diagnostic_window_minutes: int = 120,
                                 limit: int = 100, apply_sent: bool = False) -> dict:
    from .telegram_io import TelegramPool
    jobs = uncertain_evidence_jobs(db, campaign_id=campaign_id, limit=limit)
    pool = TelegramPool(settings.api_id, settings.api_hash, settings.sessions, settings.staging_chats, settings.media_cache_dir)
    await pool.connect()
    results: list[dict] = []
    reconciled: list[int] = []
    try:
        auth = await pool.authorization()
        for job in jobs:
            recorded = job.get('account_key')
            inferred = job.get('inferred_account_key')
            if recorded:
                account_candidates = [recorded]
                account_source = 'queue'
            elif inferred:
                account_candidates = [inferred]
                account_source = 'durable_attempt_or_phase_history'
            else:
                account_candidates = [k for k in pool.clients if auth.get(k, {}).get('authorized')]
                account_source = 'all_authorized_accounts'

            account_candidates = [a for a in account_candidates if a in pool.clients and auth.get(a, {}).get('authorized')]
            if not account_candidates:
                r = EvidenceMatch(
                    queue_id=int(job['id']), account_key=recorded, group_id=int(job['group_id']),
                    group_name=str(job.get('group_name') or job['group_id']), expected_mode=str(job.get('mode') or 'unknown'),
                    expected_media_count=int(job.get('expected_media_count') or 0), attempt_at=str(job.get('attempt_at') or ''),
                    window_start='', window_end='', reason='no recorded/inferred authorized account is available',
                    account_source=account_source,
                )
                results.append(r.to_dict()); continue

            attempt = _dt(job.get('attempt_at'))
            strict_start = attempt - timedelta(minutes=max(1, int(window_minutes)))
            strict_end = attempt + timedelta(minutes=max(1, int(window_minutes)))
            diag_start = attempt - timedelta(minutes=max(int(window_minutes), int(diagnostic_window_minutes)))
            diag_end = attempt + timedelta(minutes=max(int(window_minutes), int(diagnostic_window_minutes)))
            per_account: list[tuple[str, EvidenceMatch]] = []
            scan_errors: list[str] = []
            for account in account_candidates:
                client = pool.clients[account]
                try:
                    entity = await client.get_entity(int(job['group_id']))
                    diag_history = await _history_window(client, entity, start=diag_start, end=diag_end, limit=800)
                    strict_history = [m for m in diag_history if strict_start <= _message_date(m) <= strict_end]
                    match = evaluate_messages(job, strict_history, window_minutes=window_minutes)
                    diagnostic = evaluate_diagnostic_messages(job, diag_history, window_minutes=diagnostic_window_minutes)
                    match.account_key = account
                    match.account_source = account_source
                    match.diagnostic_candidate_count = int(diagnostic['candidate_count'])
                    match.diagnostic_exact_count = int(diagnostic['exact_match_count'])
                    match.diagnostic_nearest_seconds = diagnostic['nearest_seconds']
                    match.diagnostic_reason = diagnostic['reason']
                    per_account.append((account, match))
                except Exception as exc:
                    scan_errors.append(f'{account}:{type(exc).__name__}:{exc}')

            exact = [(a,m) for a,m in per_account if m.confidence == 'high']
            ambiguous = [(a,m) for a,m in per_account if m.confidence == 'ambiguous']
            if len(exact) == 1 and not ambiguous:
                account, match = exact[0]
                if len(account_candidates) > 1:
                    match.reason += '; unique across all authorized accounts'
            elif len(exact) > 1 or ambiguous:
                # Never auto-resolve when more than one account/payload could explain the send.
                base = (ambiguous[0][1] if ambiguous else exact[0][1])
                match = base
                match.confidence = 'ambiguous'
                match.matched_message_ids = []
                match.reason = 'multiple exact/ambiguous matches across account candidates; automatic reconciliation blocked'
                account = None
            elif per_account:
                # Pick the most informative diagnostic result for reporting only.
                account, match = max(per_account, key=lambda x: (x[1].diagnostic_exact_count, x[1].diagnostic_candidate_count,
                                                                  -(x[1].diagnostic_nearest_seconds or 10**9)))
                if len(account_candidates) > 1:
                    match.reason += '; scanned all authorized accounts'
            else:
                account = None
                match = EvidenceMatch(
                    queue_id=int(job['id']), account_key=recorded, group_id=int(job['group_id']),
                    group_name=str(job.get('group_name') or job['group_id']), expected_mode=str(job.get('mode') or 'unknown'),
                    expected_media_count=int(job.get('expected_media_count') or 0), attempt_at=attempt.isoformat(timespec='seconds'),
                    window_start=strict_start.isoformat(timespec='seconds'), window_end=strict_end.isoformat(timespec='seconds'),
                    reason='Telegram history scan failed for all account candidates: ' + '; '.join(scan_errors)[:800],
                    account_source=account_source,
                )
            item = match.to_dict()
            item['account_candidates'] = list(account_candidates)
            item['scan_errors'] = list(scan_errors)
            if apply_sent and match.confidence == 'high' and match.matched_message_ids and account:
                evidence = (
                    f"Automated Telegram history evidence: unique exact outgoing match; account={account}; "
                    f"account_source={account_source}; group_id={job['group_id']}; message_ids={match.matched_message_ids}; "
                    f"grouped_id={match.matched_grouped_id}; matched_at={match.matched_at}; "
                    f"strict_window={match.window_start}..{match.window_end}"
                )
                rec = reconcile_uncertain(db, int(job['id']), 'sent', evidence=evidence,
                                          confirmation=CONFIRM_SENT, actor='telegram-history-scanner')
                item['reconciliation'] = rec
                reconciled.append(int(job['id']))
            results.append(item)
    finally:
        await pool.disconnect()
    return {
        'automatic_not_sent': False,
        'apply_sent': bool(apply_sent),
        'jobs_scanned': len(jobs),
        'high_confidence_matches': sum(1 for r in results if r.get('confidence') == 'high'),
        'ambiguous_matches': sum(1 for r in results if r.get('confidence') == 'ambiguous'),
        'auto_reconciled_sent': reconciled,
        'remaining_uncertain': len(uncertain_evidence_jobs(db, campaign_id=campaign_id, limit=500)),
        'results': results,
    }
