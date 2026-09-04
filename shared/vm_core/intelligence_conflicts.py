from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .intelligence_contracts import IntelligenceRecord
from .intelligence_replay import intelligence_fingerprint


@dataclass(frozen=True, slots=True)
class ConflictResult:
    duplicate_fingerprints: tuple[str, ...]
    contradictory_pairs: tuple[tuple[str, str], ...]


def _polarity(record: IntelligenceRecord) -> str | None:
    value = record.attributes.get("polarity")
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"positive", "negative", "neutral"}:
        return text
    return None


def detect_conflicts(records: Iterable[IntelligenceRecord]) -> ConflictResult:
    """Detect exact duplicates and explicit polarity contradictions.

    Contradictions are intentionally conservative: both records must have the same
    intelligence kind, record type, and subject, and must explicitly declare
    opposing positive/negative polarity. Missing or neutral polarity never becomes
    an inferred conflict.
    """
    items = tuple(records)
    seen: set[str] = set()
    duplicates: set[str] = set()
    contradictions: set[tuple[str, str]] = set()

    for record in items:
        fingerprint = intelligence_fingerprint(record)
        if fingerprint in seen:
            duplicates.add(fingerprint)
        else:
            seen.add(fingerprint)

    for index, left in enumerate(items):
        left_polarity = _polarity(left)
        if left_polarity not in {"positive", "negative"}:
            continue
        for right in items[index + 1 :]:
            if (
                left.kind != right.kind
                or left.subject_type != right.subject_type
                or left.subject_id != right.subject_id
                or left.record_type != right.record_type
            ):
                continue
            right_polarity = _polarity(right)
            if {left_polarity, right_polarity} == {"positive", "negative"}:
                pair = tuple(
                    sorted(
                        (
                            intelligence_fingerprint(left),
                            intelligence_fingerprint(right),
                        )
                    )
                )
                contradictions.add(pair)

    return ConflictResult(
        duplicate_fingerprints=tuple(sorted(duplicates)),
        contradictory_pairs=tuple(sorted(contradictions)),
    )
