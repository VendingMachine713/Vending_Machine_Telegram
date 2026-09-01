from __future__ import annotations

from . import __version__
from .analytics import analytics_snapshot
from .db import Database
from .recommendations import list_recommendations


def _n(d, key):
    return int((d or {}).get(key, 0) or 0)


def report_text(db: Database, hours: int = 24, *, title: str | None = None, recommendation_limit: int = 5) -> str:
    a=analytics_snapshot(db,hours); q=a['queue_status']; ds=a['destination_state']; lc=a['campaign_lifecycle']
    lines=[title or f'SMART AUTO POSTER V{__version__} â€” {hours}H REPORT','']
    lines += [
        f"Sent: {_n(q,'sent')} | Failed: {_n(q,'failed')+_n(q,'quarantined')} | Deferred: {_n(q,'deferred')} | Uncertain: {_n(q,'uncertain')}",
        f"Success rate: {a['success_rate']:.2f}%",
        f"Campaigns: active {_n(lc,'active')} | paused {_n(lc,'paused')} | draft {_n(lc,'draft')} | ready {_n(lc,'ready')}",
        f"Destinations: enabled {_n(ds,'enabled')} | review {_n(ds,'review')} | quarantined {_n(ds,'quarantined')} | protected {_n(ds,'protected')}",
    ]
    if a['account_health']:
        lines.append('')
        lines.append('Accounts:')
        for r in a['account_health']:
            state='OK' if r.get('authorized') else 'AUTH NEEDED'
            lines.append(f"- {r['account_key']}: {state}, health {int(r.get('health_score') or 0)}/100")
    recs=list_recommendations(db,'open',recommendation_limit)
    if recs:
        lines.append(''); lines.append('Recommendations / attention:')
        for r in recs:
            lines.append(f"- [{r['severity']}] {r['title']}")
    return '\n'.join(lines)


def daily_report_text(db: Database) -> str:
    return report_text(db,24,title=f'SMART AUTO POSTER V{__version__} â€” DAILY')


def weekly_report_text(db: Database) -> str:
    return report_text(db,168,title=f'SMART AUTO POSTER V{__version__} â€” WEEKLY',recommendation_limit=10)
