from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
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
_CANONICAL_DIGEST_LENGTH = 24


@dataclass(frozen=True, slots=True)
class ProvenanceResult:
    valid: bool
    event_id: int | None
    expected_source: str
    stored_source: str | None
    reason: str
    event_type: str | None = None
    canonical_subject_id: str | None = None


def _registry_source(source: str) -> str | None:
    if source in SOURCE_TRUST_REGISTRY:
        return source
    if source.startswith("vm_core."):
        return "vm_core"
    return None


def source_trust(source: str) -> float:
    """Return the governed default trust weight for one intelligence producer.

    VM Core subcomponents inherit the explicit ``vm_core`` trust entry so canonical
    producers do not accidentally fall back to unknown-source trust merely because
    their audit source is namespaced (for example ``vm_core.learning``).
    Unknown sources deliberately receive a conservative non-zero default.
    """
    name = source.strip()
    if not name:
        raise IntelligenceContractError("source is required")
    registry_key = _registry_source(name)
    return clamp01(
        SOURCE_TRUST_REGISTRY[registry_key]
        if registry_key is not None
        else DEFAULT_SOURCE_TRUST
    )


def canonical_entity_id(
    entity_type: str,
    native_id: str | int,
    *,
    namespace: str = "telegram",
) -> str:
    """Build a stable, non-secret canonical entity identifier.

    Native IDs are hashed so cross-bot correlation can use one stable key without
    repeatedly copying raw platform identifiers into intelligence surfaces.
    """
    kind = entity_type.strip().lower().replace(" ", "_")
    ns = namespace.strip().lower().replace(" ", "_")
    value = str(native_id).strip()
    if not kind or not ns or not value:
        raise IntelligenceContractError("entity type, namespace and native id are required")
    digest = hashlib.sha256(f"{ns}:{kind}:{value}".encode("utf-8")).hexdigest()[:_CANONICAL_DIGEST_LENGTH]
    return f"{ns}:{kind}:{digest}"


def canonical_entity_parts(value: str | None) -> tuple[str, str, str] | None:
    """Parse a canonical entity ID without accepting native/raw identifiers."""
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 3:
        return None
    namespace, entity_type, digest = parts
    if not namespace or not entity_type or len(digest) != _CANONICAL_DIGEST_LENGTH:
        return None
    if any(char not in "0123456789abcdef" for char in digest.lower()):
        return None
    return namespace, entity_type, digest.lower()


def is_canonical_entity_id(value: str | None) -> bool:
    """Return whether a value matches the shared non-secret canonical ID shape."""
    return canonical_entity_parts(value) is not None


def _readonly_connect(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=5,
        )
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        return con
    except sqlite3.Error:
        try:
            con.close()  # type: ignore[possibly-undefined]
        except (UnboundLocalError, sqlite3.Error):
            pass
        return None


def verify_evidence_provenance(
    evidence: EvidenceRef,
    *,
    root: Path | None = None,
) -> ProvenanceResult:
    """Verify one EvidenceRef against the event ledger without mutating state.

    Verification is deliberately read-only: it never initializes, migrates or
    creates the platform database. Missing stores/tables fail closed with explicit
    reasons. Evidence without an event ID remains externally referenced and is not
    falsely marked as verified.
    """
    if evidence.event_id is None:
        return ProvenanceResult(
            valid=False,
            event_id=None,
            expected_source=evidence.source,
            stored_source=None,
            reason="external_reference_unverified",
        )

    db_path = PlatformDB(root=root or project_root()).path
    con = _readonly_connect(db_path)
    if con is None:
        return ProvenanceResult(
            valid=False,
            event_id=evidence.event_id,
            expected_source=evidence.source,
            stored_source=None,
            reason="event_store_unavailable",
        )
    try:
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        if table is None:
            return ProvenanceResult(
                valid=False,
                event_id=evidence.event_id,
                expected_source=evidence.source,
                stored_source=None,
                reason="events_table_missing",
            )
        row = con.execute(
            "SELECT id,source,event_type,subject_id FROM events WHERE id=?",
            (int(evidence.event_id),),
        ).fetchone()
    except sqlite3.Error:
        return ProvenanceResult(
            valid=False,
            event_id=evidence.event_id,
            expected_source=evidence.source,
            stored_source=None,
            reason="event_store_read_error",
        )
    finally:
        con.close()

    if row is None:
        return ProvenanceResult(
            valid=False,
            event_id=evidence.event_id,
            expected_source=evidence.source,
            stored_source=None,
            reason="event_not_found",
        )

    stored_source = str(row["source"])
    canonical_subject = (
        str(row["subject_id"])
        if is_canonical_entity_id(row["subject_id"])
        else None
    )
    if stored_source != evidence.source:
        return ProvenanceResult(
            valid=False,
            event_id=evidence.event_id,
            expected_source=evidence.source,
            stored_source=stored_source,
            reason="source_mismatch",
            event_type=str(row["event_type"]),
            canonical_subject_id=canonical_subject,
        )

    return ProvenanceResult(
        valid=True,
        event_id=evidence.event_id,
        expected_source=evidence.source,
        stored_source=stored_source,
        reason="verified",
        event_type=str(row["event_type"]),
        canonical_subject_id=canonical_subject,
    )


def verify_record_evidence(
    evidence: Iterable[EvidenceRef],
    *,
    root: Path | None = None,
) -> list[ProvenanceResult]:
    return [verify_evidence_provenance(item, root=root) for item in evidence]


def trust_foundation_summary(
    *,
    root: Path | None = None,
    limit: int = 1000,
) -> dict[str, object]:
    """Return passive trust/canonical-ID health for operator and CI surfaces."""
    root = root or project_root()
    result: dict[str, object] = {
        "event_store_status": "UNAVAILABLE",
        "intelligence_events_checked": 0,
        "canonical_subject_events": 0,
        "noncanonical_subject_events": 0,
        "subjectless_events": 0,
        "canonical_subject_coverage": None,
        "registered_sources": dict(SOURCE_TRUST_REGISTRY),
        "default_unknown_source_trust": DEFAULT_SOURCE_TRUST,
        "vm_core_namespaced_inheritance": True,
        "canonical_digest_length": _CANONICAL_DIGEST_LENGTH,
        "read_only": True,
        "automatic_trust_change": False,
        "automatic_rule_change": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }
    con = _readonly_connect(PlatformDB(root=root).path)
    if con is None:
        return result
    try:
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        if table is None:
            result["event_store_status"] = "EVENTS_TABLE_MISSING"
            return result
        rows = con.execute(
            "SELECT subject_id FROM events WHERE event_type LIKE 'intelligence.%' "
            "ORDER BY id DESC LIMIT ?",
            (max(1, min(5000, int(limit))),),
        ).fetchall()
    except (sqlite3.Error, TypeError, ValueError):
        result["event_store_status"] = "READ_ERROR"
        return result
    finally:
        con.close()

    canonical = 0
    noncanonical = 0
    subjectless = 0
    for row in rows:
        value = row["subject_id"]
        if value is None or not str(value).strip():
            subjectless += 1
        elif is_canonical_entity_id(str(value)):
            canonical += 1
        else:
            noncanonical += 1
    with_subject = canonical + noncanonical
    result.update(
        {
            "event_store_status": "OK",
            "intelligence_events_checked": len(rows),
            "canonical_subject_events": canonical,
            "noncanonical_subject_events": noncanonical,
            "subjectless_events": subjectless,
            "canonical_subject_coverage": (
                round(canonical / with_subject, 4) if with_subject else None
            ),
        }
    )
    return result
