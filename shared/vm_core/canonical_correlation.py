from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .intelligence_audit import AuditQuery, query_intelligence_events
from .intelligence_contracts import EvidenceRef, IntelligenceKind, IntelligenceRecord
from .intelligence_trust import verify_record_evidence
from .paths import project_root
from .publisher import BotEventPublisher


_RELATIONSHIP_TYPE = "intelligence.signal.relationship_dormant_presence"
_SEARCH_TYPE = "intelligence.signal.search_activity_spike"
_GUARD_TYPE = "intelligence.signal.guard_risk_elevated"
_INFERENCE_TYPE = "relationship_reengagement_opportunity"
_GUARD_MAX_AGE = timedelta(hours=6)


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def _recent_guard(row: dict[str, Any] | None, *, now: datetime) -> dict[str, Any] | None:
    if row is None:
        return None
    observed = _parse_time(row.get("created_at_utc"))
    if observed is None or now - observed > _GUARD_MAX_AGE:
        return None
    return row


def correlate_relationship_search(*, root: Path | None = None, limit: int = 1000) -> dict[str, int]:
    """Correlate canonical dormant-relationship and Search activity with optional Guard risk.

    During migration, opportunity creation intentionally mirrors the established
    legacy path by requiring a *dormant* relationship. Cooling relationships remain
    bridged canonically but are not promoted to opportunity inference until shadow
    parity is proven and that expansion is separately governed.
    """
    root = root or project_root()
    now = datetime.now(timezone.utc)
    relationship_rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_RELATIONSHIP_TYPE,
            source="VM_Relationship_Manager",
            subject_type="chat",
            limit=limit,
        ),
        root=root,
    )
    search_rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_SEARCH_TYPE,
            source="Universal_Search",
            subject_type="chat",
            limit=limit,
        ),
        root=root,
    )
    guard_rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix=_GUARD_TYPE,
            source="VM_Guard",
            subject_type="chat",
            limit=limit,
        ),
        root=root,
    )
    relationships = _latest_by_subject(relationship_rows)
    searches = _latest_by_subject(search_rows)
    guards = _latest_by_subject(guard_rows)
    result = {
        "matched_subjects": 0,
        "published": 0,
        "guard_suppressed": 0,
        "skipped_existing": 0,
        "invalid_evidence": 0,
    }

    for subject_id in sorted(set(relationships) & set(searches)):
        result["matched_subjects"] += 1
        relationship = relationships[subject_id]
        search = searches[subject_id]
        guard = _recent_guard(guards.get(subject_id), now=now)
        supporting_rows = [relationship, search]
        if guard is not None:
            supporting_rows.append(guard)
        event_ids = tuple(int(row["id"]) for row in supporting_rows)
        signature = _support_signature(event_ids)
        if _already_correlated(root, subject_id, signature):
            result["skipped_existing"] += 1
            continue

        evidence_items = tuple(
            item for item in (_evidence_from_event(row) for row in supporting_rows) if item is not None
        )
        if len(evidence_items) != len(supporting_rows):
            result["invalid_evidence"] += 1
            continue
        provenance = verify_record_evidence(evidence_items, root=root)
        if not all(item.valid for item in provenance):
            result["invalid_evidence"] += 1
            continue

        relationship_attributes = _payload(relationship).get("attributes") or {}
        search_attributes = _payload(search).get("attributes") or {}
        guard_attributes = _payload(guard).get("attributes") if guard is not None else {}
        try:
            relationship_score = float(relationship_attributes.get("score") or 0.0)
            activity_score = float(search_attributes.get("score") or 0.0)
            guard_score = float((guard_attributes or {}).get("score") or 0.0)
        except (TypeError, ValueError):
            result["invalid_evidence"] += 1
            continue

        base_score = min(100.0, (activity_score * 0.55) + (relationship_score * 0.45))
        suppressed = guard is not None and guard_score >= 60.0
        opportunity_score = min(base_score, 40.0) if suppressed else base_score
        if suppressed:
            result["guard_suppressed"] += 1

        rationale = (
            "A dormant relationship is present in a chat whose indexed activity is materially "
            "above its recent baseline"
        )
        if suppressed:
            rationale += "; recent VM Guard risk suppresses progression beyond review"

        record = IntelligenceRecord.from_evidence(
            kind=IntelligenceKind.INFERENCE,
            record_type=_INFERENCE_TYPE,
            source="vm_core",
            subject_type="chat",
            subject_id=subject_id,
            rationale=rationale,
            evidence=evidence_items,
            half_life_seconds=48 * 3600,
            attributes={
                "support_signature": signature,
                "supporting_event_ids": sorted(event_ids),
                "relationship_state": "dormant",
                "relationship_score": relationship_attributes.get("relationship_score"),
                "activity_ratio": search_attributes.get("ratio"),
                "guard_risk_score": guard_score,
                "guard_evidence_recent": guard is not None,
                "suppressed": suppressed,
                "opportunity_score": opportunity_score,
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
