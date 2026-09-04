from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from .db import PlatformDB
from .intelligence_contracts import EvidenceRef, IntelligenceContractError, clamp01
from .paths import project_root


DEFAULT_SOURCE_TRUST = 0.50
SOURCE_TRUST_REGISTRY: dict[str, float] = {
    "VM_Guard": 0.90,
    "Universal_Search": 0.80,
    "VM_Relationship_Manager": 0.80,
    "Smart_Auto_Poster_V2": 0.85,
    "Admin_Command_Centre": 0.95,
    "vm_core": 0.95,
}


@dataclass(frozen=True, slots=True)
class ProvenanceResult:
    valid: bool
    event_id: int | None
    expected_source: str
    stored_source: str | None
    reason: str


def source_trust(source: str) -> float:
    """Return the governed default trust weight for one intelligence producer.

    Unknown sources deliberately receive a conservative non-zero default rather
    than inheriting full trust. Callers may later layer calibrated trust above
    this registry without changing historical evidence records.
    """
    name = source.strip()
    if not name:
        raise IntelligenceContractError("source is required")
    return clamp01(SOURCE_TRUST_REGISTRY.get(name, DEFAULT_SOURCE_TRUST))


def canonical_entity_id(entity_type: str, native_id: str | int, *, namespace: str = "telegram") -> str:
    """Build a stable, non-secret canonical entity identifier.

    Native IDs are hashed so cross-bot correlation can use one stable key without
    repeatedly copying raw platform identifiers into intelligence surfaces.
    """
    kind = entity_type.strip().lower().replace(" ", "_")
    ns = namespace.strip().lower().replace(" ", "_")
    value = str(native_id).strip()
    if not kind or not ns or not value:
        raise IntelligenceContractError("entity type, namespace and native id are required")
    digest = hashlib.sha256(f"{ns}:{kind}:{value}".encode("utf-8")).hexdigest()[:24]
    return f"{ns}:{kind}:{digest}"


def verify_evidence_provenance(
    evidence: EvidenceRef,
    *,
    root: Path | None = None,
) -> ProvenanceResult:
    """Verify an EvidenceRef against the durable VM event store when possible.

    Evidence with an event ID must resolve to an existing event whose source
    matches the evidence source. Evidence without an event ID remains externally
    referenced and is not falsely marked as verified.
    """
    if evidence.event_id is None:
        return ProvenanceResult(
            valid=False,
            event_id=None,
            expected_source=evidence.source,
            stored_source=None,
            reason="external_reference_unverified",
        )

    db = PlatformDB(root=root or project_root())
    db.init()
    with db.connect() as con:
        row = con.execute(
            "SELECT id, source FROM events WHERE id=?",
            (int(evidence.event_id),),
        ).fetchone()

    if row is None:
        return ProvenanceResult(
            valid=False,
            event_id=evidence.event_id,
            expected_source=evidence.source,
            stored_source=None,
            reason="event_not_found",
        )

    stored_source = str(row["source"])
    if stored_source != evidence.source:
        return ProvenanceResult(
            valid=False,
            event_id=evidence.event_id,
            expected_source=evidence.source,
            stored_source=stored_source,
            reason="source_mismatch",
        )

    return ProvenanceResult(
        valid=True,
        event_id=evidence.event_id,
        expected_source=evidence.source,
        stored_source=stored_source,
        reason="verified",
    )


def verify_record_evidence(
    evidence: Iterable[EvidenceRef],
    *,
    root: Path | None = None,
) -> list[ProvenanceResult]:
    return [verify_evidence_provenance(item, root=root) for item in evidence]
