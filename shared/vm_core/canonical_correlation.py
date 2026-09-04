from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .intelligence_audit import AuditQuery, query_intelligence_events
from .intelligence_contracts import EvidenceRef, IntelligenceKind, IntelligenceRecord
from .intelligence_trust import verify_record_evidence
from .paths import project_root
from .publisher import BotEventPublisher


_RELATIONSHIP_TYPES = {
    "intelligence.signal.relationship_dormant_presence",
    "intelligence.signal.relationship_cooling_presence",
}
_SEARCH_TYPE = "intelligence.signal.search_activity_spike"
_INFERENCE_TYPE = "relationship_reengagement_opportunity"


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _latest_by_subject(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        subject_id = str(row.get("subject_id") or "")
        if not subject_id:
            continue
        current = latest.get(subject_id)
        if current is None or int(row.get("id") or 0) > int(current.get("id") or 0):
            latest[subject_id] = row
    return latest


def _support_signature(event_ids: tuple[int, ...]) -> str:
    body = ":".join(str(value) for value in sorted(event_ids))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _already_correlated(root: Path, subject_id: str, signature: str) -> bool:
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=f"intelligence.inference.{_INFERENCE_TYPE}",
            source="vm_core",
            subject_type="chat",
            subject_id=subject_id,
            limit=20,
        ),
        root=root,
    )
    for row in rows:
        attributes = _payload(row).get("attributes")
        if isinstance(attributes, dict) and attributes.get("support_signature") == signature:
            return True
    return False


def _evidence_from_event(row: dict[str, Any]) -> EvidenceRef | None:
    payload = _payload(row)
    try:
        confidence = float(payload.get("confidence"))
        event_id = int(row.get("id"))
    except (TypeError, ValueError):
        return None
    observed_at = str(row.get("created_at_utc") or "").strip()
    source = str(row.get("source") or "").strip()
    if not source or not observed_at or event_id <= 0:
        return None
    return EvidenceRef(
        source=source,
        observed_at_utc=observed_at,
        confidence=confidence,
        source_trust=1.0,
        event_id=event_id,
        reference=f"canonical_event:{event_id}",
        attributes={"event_type": row.get("event_type")},
    )


def correlate_relationship_search(*, root: Path | None = None, limit: int = 1000) -> dict[str, int]:
    """Correlate canonical Relationship Manager state with Universal Search activity.

    Produces an inference only. It does not create a recommendation or execute an
    action. Supporting evidence points to durable canonical event IDs and is
    provenance-verified before publication.
    """
    root = root or project_root()
    relationship_rows = [
        row
        for row in query_intelligence_events(
            AuditQuery(
                event_type_prefix="intelligence.signal.relationship_",
                source="VM_Relationship_Manager",
                subject_type="chat",
                limit=limit,
            ),
            root=root,
        )
        if row.get("event_type") in _RELATIONSHIP_TYPES
    ]
    search_rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_SEARCH_TYPE,
            source="Universal_Search",
            subject_type="chat",
            limit=limit,
        ),
        root=root,
    )
    relationships = _latest_by_subject(relationship_rows)
    searches = _latest_by_subject(search_rows)
    result = {"matched_subjects": 0, "published": 0, "skipped_existing": 0, "invalid_evidence": 0}

    for subject_id in sorted(set(relationships) & set(searches)):
        result["matched_subjects"] += 1
        relationship = relationships[subject_id]
        search = searches[subject_id]
        event_ids = (int(relationship["id"]), int(search["id"]))
        signature = _support_signature(event_ids)
        if _already_correlated(root, subject_id, signature):
            result["skipped_existing"] += 1
            continue

        evidence_items = tuple(
            item
            for item in (_evidence_from_event(relationship), _evidence_from_event(search))
            if item is not None
        )
        if len(evidence_items) != 2:
            result["invalid_evidence"] += 1
            continue
        provenance = verify_record_evidence(evidence_items, root=root)
        if not all(item.valid for item in provenance):
            result["invalid_evidence"] += 1
            continue

        relationship_payload = _payload(relationship)
        search_payload = _payload(search)
        relationship_attributes = relationship_payload.get("attributes") or {}
        search_attributes = search_payload.get("attributes") or {}
        record = IntelligenceRecord.from_evidence(
            kind=IntelligenceKind.INFERENCE,
            record_type=_INFERENCE_TYPE,
            source="vm_core",
            subject_type="chat",
            subject_id=subject_id,
            rationale=(
                "A cooling or dormant relationship is present in a chat whose indexed "
                "activity is materially above its recent baseline"
            ),
            evidence=evidence_items,
            half_life_seconds=48 * 3600,
            attributes={
                "support_signature": signature,
                "supporting_event_ids": sorted(event_ids),
                "relationship_state": relationship_attributes.get("lifecycle_stage"),
                "relationship_score": relationship_attributes.get("relationship_score"),
                "activity_ratio": search_attributes.get("ratio"),
                "opportunity_class": "reengagement",
                "polarity": "positive",
                "recommendation_created": False,
                "automatic_execution": False,
            },
        )
        if BotEventPublisher("vm_core", root).intelligence(record) is not None:
            result["published"] += 1
        else:
            result["invalid_evidence"] += 1
    return result
