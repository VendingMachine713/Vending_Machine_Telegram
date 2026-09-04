from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .db import PlatformDB
from .intelligence_contracts import IntelligenceRecord
from .paths import project_root


@dataclass(frozen=True, slots=True)
class ReplayComparison:
    baseline_count: int
    candidate_count: int
    added_fingerprints: tuple[str, ...]
    removed_fingerprints: tuple[str, ...]
    unchanged_count: int


def _stable_hash(body: dict[str, Any]) -> str:
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json(value: Any) -> Any:
    """Normalize JSON fields so formatting/key order cannot change fingerprints."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def intelligence_fingerprint(record: IntelligenceRecord) -> str:
    """Return a stable fingerprint for duplicate detection and replay comparison."""
    return _stable_hash(
        {
            "kind": record.kind.value,
            "record_type": record.record_type,
            "source": record.source,
            "subject_type": record.subject_type,
            "subject_id": record.subject_id,
            "rationale": record.rationale,
            "evidence": [item.as_dict() for item in record.evidence],
            "attributes": record.attributes,
            "schema_version": record.schema_version,
        }
    )


def event_fingerprint(row: dict[str, Any]) -> str:
    """Fingerprint one stored intelligence event without depending on database IDs.

    Stored JSON is parsed before hashing, so semantically identical payloads do not
    appear different merely because key order or whitespace changed.
    """
    return _stable_hash(
        {
            "event_type": row.get("event_type"),
            "source": row.get("source"),
            "subject_type": row.get("subject_type"),
            "subject_id": row.get("subject_id"),
            "payload": _canonical_json(row.get("payload_json")),
            "evidence": _canonical_json(row.get("evidence_json")),
        }
    )


def replay_dataset(*, root: Path | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    """Return a bounded historical intelligence dataset without mutating storage.

    Replay inspection must never initialize, migrate, or create the platform DB.
    A missing database or pre-intelligence schema therefore returns an empty set.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    if not db.path.exists():
        return []
    try:
        rows = db.events(limit=max(1, int(limit)))
    except sqlite3.OperationalError:
        return []
    return [
        row
        for row in rows
        if str(row.get("event_type") or "").startswith("intelligence.")
    ]


def compare_replay(
    baseline: Iterable[dict[str, Any]],
    candidate: Iterable[dict[str, Any]],
) -> ReplayComparison:
    """Compare two replay result sets using stable fingerprints only.

    This function is passive: it performs no writes and grants no execution authority.
    Counts represent unique semantic events, intentionally suppressing exact duplicates.
    """
    baseline_set = {event_fingerprint(row) for row in baseline}
    candidate_set = {event_fingerprint(row) for row in candidate}
    added = tuple(sorted(candidate_set - baseline_set))
    removed = tuple(sorted(baseline_set - candidate_set))
    return ReplayComparison(
        baseline_count=len(baseline_set),
        candidate_count=len(candidate_set),
        added_fingerprints=added,
        removed_fingerprints=removed,
        unchanged_count=len(baseline_set & candidate_set),
    )
