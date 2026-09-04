from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .intelligence_audit import AuditQuery, query_intelligence_events
from .paths import project_root


_INFERENCE_PREFIX = "intelligence.inference.relationship_reengagement_opportunity"


@dataclass(frozen=True, slots=True)
class CanonicalEvidenceHealth:
    status: str
    total_inference_events: int
    distinct_subjects: int
    newest_event_at_utc: str | None
    oldest_event_at_utc: str | None
    newest_age_hours: float | None
    observation_span_hours: float
    events_last_24h: int
    events_last_7d: int
    events_last_30d: int
    latest_suppressed_subjects: int
    latest_suppressed_ratio: float
    stale: bool
    automatic_execution: bool = False


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def canonical_evidence_health(
    *,
    root: Path | None = None,
    now: datetime | None = None,
    stale_after_hours: float = 72.0,
    limit: int = 5000,
) -> CanonicalEvidenceHealth:
    """Return passive health metrics for the canonical shadow evidence ledger.

    The function is read-only. Missing state is treated as no evidence and never
    creates a platform database.
    """
    root = root or project_root()
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_INFERENCE_PREFIX,
            source="vm_core",
            subject_type="chat",
            limit=max(1, int(limit)),
        ),
        root=root,
    )

    dated_rows: list[tuple[dict[str, Any], datetime]] = []
    for row in rows:
        created = _parse_utc(row.get("created_at_utc"))
        if created is not None:
            dated_rows.append((row, created))

    if not dated_rows:
        return CanonicalEvidenceHealth(
            status="NO_EVIDENCE",
            total_inference_events=len(rows),
            distinct_subjects=0,
            newest_event_at_utc=None,
            oldest_event_at_utc=None,
            newest_age_hours=None,
            observation_span_hours=0.0,
            events_last_24h=0,
            events_last_7d=0,
            events_last_30d=0,
            latest_suppressed_subjects=0,
            latest_suppressed_ratio=0.0,
            stale=True,
        )

    dated_rows.sort(key=lambda item: item[1], reverse=True)
    newest = dated_rows[0][1]
    oldest = dated_rows[-1][1]
    latest_by_subject: dict[str, dict[str, Any]] = {}
    for row, _created in dated_rows:
        subject = str(row.get("subject_id") or "").strip()
        if subject and subject not in latest_by_subject:
            latest_by_subject[subject] = row

    suppressed = 0
    for row in latest_by_subject.values():
        attributes = _payload(row).get("attributes")
        if isinstance(attributes, dict) and bool(attributes.get("suppressed")):
            suppressed += 1

    def recent_count(hours: float) -> int:
        return sum(1 for _row, created in dated_rows if (now - created).total_seconds() <= hours * 3600)

    age_hours = max(0.0, (now - newest).total_seconds() / 3600.0)
    span_hours = max(0.0, (newest - oldest).total_seconds() / 3600.0)
    subject_count = len(latest_by_subject)
    suppressed_ratio = suppressed / subject_count if subject_count else 0.0
    stale = age_hours > max(1.0, float(stale_after_hours))

    return CanonicalEvidenceHealth(
        status="STALE" if stale else "ACTIVE_SHADOW",
        total_inference_events=len(rows),
        distinct_subjects=subject_count,
        newest_event_at_utc=newest.isoformat(),
        oldest_event_at_utc=oldest.isoformat(),
        newest_age_hours=age_hours,
        observation_span_hours=span_hours,
        events_last_24h=recent_count(24),
        events_last_7d=recent_count(7 * 24),
        events_last_30d=recent_count(30 * 24),
        latest_suppressed_subjects=suppressed,
        latest_suppressed_ratio=suppressed_ratio,
        stale=stale,
    )


def canonical_evidence_health_summary(**kwargs: Any) -> dict[str, Any]:
    return asdict(canonical_evidence_health(**kwargs))
