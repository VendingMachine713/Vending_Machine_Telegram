from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
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


def intelligence_fingerprint(record: IntelligenceRecord) -> str:
    """Return a stable fingerprint for duplicate detection and replay comparison."""
    body = {
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
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def event_fingerprint(row: dict[str, Any]) -> str:
    """Fingerprint one stored intelligence event without depending on database IDs."""
    body = {
        "event_type": row.get("event_type"),
        "source": row.get("source"),
        "subject_type": row.get("subject_type"),
        "subject_id": row.get("subject_id"),
        "payload_json": row.get("payload_json"),
        "evidence_json": row.get("evidence_json"),
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def replay_dataset(*, root: Path | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    """Return a bounded, read-only historical intelligence dataset for shadow evaluation."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    rows = db.events(limit=max(1, int(limit)))
    return [row for row in rows if str(row.get("event_type") or "").startswith("intelligence.")]


def compare_replay(
    baseline: Iterable[dict[str, Any]],
    candidate: Iterable[dict[str, Any]],
) -> ReplayComparison:
    """Compare two replay result sets using stable fingerprints only.

    This function is passive: it performs no writes and grants no execution authority.
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
