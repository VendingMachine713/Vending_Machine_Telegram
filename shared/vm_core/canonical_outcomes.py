from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .intelligence_audit import AuditQuery, query_intelligence_events
from .intelligence_contracts import EvidenceRef, IntelligenceKind, IntelligenceRecord
from .intelligence_trust import verify_record_evidence
from .paths import project_root
from .publisher import BotEventPublisher


_INFERENCE_TYPE = "intelligence.inference.relationship_reengagement_opportunity"
_OUTCOME_TYPE = "intelligence.outcome.relationship_reengagement_opportunity"
_ALLOWED_OUTCOMES = {"POSITIVE", "NEUTRAL", "NEGATIVE", "UNKNOWN"}


class CanonicalOutcomeError(ValueError):
    """Raised when canonical inference outcome data is invalid or ambiguous."""


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _find_inference(root: Path, inference_event_id: int) -> dict[str, Any]:
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_INFERENCE_TYPE,
            source="vm_core",
            subject_type="chat",
            limit=5000,
        ),
        root=root,
    )
    for row in rows:
        if int(row.get("id") or 0) == inference_event_id:
            return row
    raise CanonicalOutcomeError(f"canonical inference event not found: {inference_event_id}")


def _existing_outcome(root: Path, inference_event_id: int) -> dict[str, Any] | None:
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_OUTCOME_TYPE,
            source="vm_core",
            subject_type="chat",
            limit=5000,
        ),
        root=root,
    )
    for row in rows:
        attributes = _payload(row).get("attributes")
        if not isinstance(attributes, dict):
            continue
        try:
            target_id = int(attributes.get("inference_event_id") or 0)
        except (TypeError, ValueError):
            continue
        if target_id == inference_event_id:
            return row
    return None


def record_canonical_inference_outcome(
    inference_event_id: int,
    outcome_type: str,
    *,
    value_score: float = 0.0,
    confidence: float = 1.0,
    actor: str = "operator",
    note: str | None = None,
    root: Path | None = None,
) -> int:
    """Record one verified outcome for a canonical shadow inference.

    Outcomes are stored as canonical events and may support later calibration. This
    function does not alter scoring rules, recommendations, Telegram state or any
    execution policy.
    """
    root = root or project_root()
    try:
        inference_event_id = int(inference_event_id)
    except (TypeError, ValueError) as exc:
        raise CanonicalOutcomeError("inference_event_id must be an integer") from exc
    if inference_event_id <= 0:
        raise CanonicalOutcomeError("inference_event_id must be positive")

    normalized = str(outcome_type or "").strip().upper()
    if normalized not in _ALLOWED_OUTCOMES:
        raise CanonicalOutcomeError(f"unsupported outcome type: {outcome_type}")
    if _existing_outcome(root, inference_event_id) is not None:
        raise CanonicalOutcomeError(f"outcome already recorded for inference: {inference_event_id}")

    inference = _find_inference(root, inference_event_id)
    subject_id = str(inference.get("subject_id") or "").strip()
    observed_at = str(inference.get("created_at_utc") or "").strip()
    if not subject_id or not observed_at:
        raise CanonicalOutcomeError("inference is missing canonical subject or timestamp")

    confidence = max(0.0, min(1.0, float(confidence)))
    value_score = max(-100.0, min(100.0, float(value_score)))
    actor = str(actor or "").strip() or "operator"
    evidence = EvidenceRef(
        source="vm_core",
        observed_at_utc=observed_at,
        confidence=confidence,
        source_trust=1.0,
        event_id=inference_event_id,
        reference=f"canonical_inference:{inference_event_id}",
        attributes={"event_type": _INFERENCE_TYPE},
    )
    provenance = verify_record_evidence((evidence,), root=root)
    if not provenance or not all(item.valid for item in provenance):
        raise CanonicalOutcomeError("inference provenance verification failed")

    record = IntelligenceRecord.from_evidence(
        kind=IntelligenceKind.OUTCOME,
        record_type="relationship_reengagement_opportunity",
        source="vm_core",
        subject_type="chat",
        subject_id=subject_id,
        rationale="Verified outcome recorded for a canonical shadow inference",
        evidence=(evidence,),
        half_life_seconds=365 * 24 * 3600,
        attributes={
            "inference_event_id": inference_event_id,
            "outcome_type": normalized,
            "value_score": value_score,
            "actor": actor,
            "note": str(note or "")[:1000],
            "automatic_rule_change": False,
            "recommendation_created": False,
            "automatic_execution": False,
        },
    )
    event_id = BotEventPublisher("vm_core", root).intelligence(record)
    if event_id is None:
        raise CanonicalOutcomeError("failed to publish canonical inference outcome")
    return int(event_id)


def canonical_inference_outcomes(*, root: Path | None = None, limit: int = 5000) -> list[dict[str, Any]]:
    """Return canonical inference outcome events without mutating platform state."""
    root = root or project_root()
    return query_intelligence_events(
        AuditQuery(
            event_type_prefix=_OUTCOME_TYPE,
            source="vm_core",
            subject_type="chat",
            limit=max(1, int(limit)),
        ),
        root=root,
    )
