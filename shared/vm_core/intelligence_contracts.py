from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from math import isfinite
from typing import Any, Iterable


INTELLIGENCE_SCHEMA_VERSION = 1


class IntelligenceContractError(ValueError):
    """Raised when intelligence data violates the trust-layer contract."""


class IntelligenceKind(StrEnum):
    FACT = "fact"
    SIGNAL = "signal"
    INFERENCE = "inference"
    PREDICTION = "prediction"
    RECOMMENDATION = "recommendation"
    DECISION = "decision"
    ACTION = "action"
    OUTCOME = "outcome"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise IntelligenceContractError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise IntelligenceContractError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def clamp01(value: float) -> float:
    value = float(value)
    if not isfinite(value):
        raise IntelligenceContractError("confidence/trust values must be finite")
    return min(1.0, max(0.0, value))


def freshness_score(
    observed_at_utc: str | datetime,
    *,
    half_life_seconds: float,
    now_utc: str | datetime | None = None,
) -> float:
    """Return deterministic evidence freshness using exponential half-life decay.

    A score of 1.0 means evidence is current. A score of 0.5 means it is one
    configured half-life old. Future timestamps are treated as current rather
    than increasing confidence.
    """
    half_life_seconds = float(half_life_seconds)
    if not isfinite(half_life_seconds) or half_life_seconds <= 0:
        raise IntelligenceContractError("half_life_seconds must be positive and finite")
    observed = _as_utc(observed_at_utc)
    now = _as_utc(now_utc) if now_utc is not None else _utc_now()
    age_seconds = max(0.0, (now - observed).total_seconds())
    return 0.5 ** (age_seconds / half_life_seconds)


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Reference to one auditable observation used by VM Brain.

    ``confidence`` is source-local confidence in the observation itself.
    ``source_trust`` is VM Brain's current trust weight for that producer.
    ``importance`` weights this item relative to other evidence in one record.
    """

    source: str
    observed_at_utc: str
    confidence: float = 1.0
    source_trust: float = 1.0
    importance: float = 1.0
    event_id: int | None = None
    reference: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        source = self.source.strip()
        if not source:
            raise IntelligenceContractError("evidence source is required")
        _as_utc(self.observed_at_utc)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "confidence", clamp01(self.confidence))
        object.__setattr__(self, "source_trust", clamp01(self.source_trust))
        importance = float(self.importance)
        if not isfinite(importance) or importance <= 0:
            raise IntelligenceContractError("evidence importance must be positive and finite")
        object.__setattr__(self, "importance", importance)
        if self.event_id is not None and int(self.event_id) <= 0:
            raise IntelligenceContractError("event_id must be positive when supplied")

    def effective_confidence(
        self,
        *,
        half_life_seconds: float,
        now_utc: str | datetime | None = None,
    ) -> float:
        return clamp01(
            self.confidence
            * self.source_trust
            * freshness_score(
                self.observed_at_utc,
                half_life_seconds=half_life_seconds,
                now_utc=now_utc,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "event_id": self.event_id,
            "reference": self.reference,
            "observed_at_utc": self.observed_at_utc,
            "confidence": self.confidence,
            "source_trust": self.source_trust,
            "importance": self.importance,
            "attributes": dict(self.attributes),
        }


def evidence_confidence(
    evidence: Iterable[EvidenceRef],
    *,
    half_life_seconds: float,
    now_utc: str | datetime | None = None,
) -> float:
    """Calculate record confidence as an importance-weighted evidence mean.

    Each evidence item contributes:
      observation confidence x source trust x freshness.

    This deliberately stays deterministic and explainable so later calibration
    can compare predicted confidence with real outcomes.
    """
    items = tuple(evidence)
    if not items:
        raise IntelligenceContractError("at least one evidence item is required")
    total_weight = sum(item.importance for item in items)
    weighted = sum(
        item.importance
        * item.effective_confidence(
            half_life_seconds=half_life_seconds,
            now_utc=now_utc,
        )
        for item in items
    )
    return clamp01(weighted / total_weight)


@dataclass(frozen=True, slots=True)
class IntelligenceRecord:
    """Canonical VM Brain trust-layer record.

    Facts, signals, inferences, predictions and later decisions use one envelope
    while remaining explicitly typed. Confidence is calculated from evidence,
    never accepted as an unexplained decorative number.
    """

    kind: IntelligenceKind
    record_type: str
    source: str
    subject_type: str
    subject_id: str
    rationale: str
    evidence: tuple[EvidenceRef, ...]
    confidence: float
    freshness: float
    created_at_utc: str
    attributes: dict[str, Any] = field(default_factory=dict)
    schema_version: int = INTELLIGENCE_SCHEMA_VERSION

    @classmethod
    def from_evidence(
        cls,
        *,
        kind: IntelligenceKind | str,
        record_type: str,
        source: str,
        subject_type: str,
        subject_id: str | int,
        rationale: str,
        evidence: Iterable[EvidenceRef],
        half_life_seconds: float,
        now_utc: str | datetime | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> "IntelligenceRecord":
        try:
            normalized_kind = kind if isinstance(kind, IntelligenceKind) else IntelligenceKind(str(kind).lower())
        except ValueError as exc:
            raise IntelligenceContractError(f"unsupported intelligence kind: {kind!r}") from exc

        items = tuple(evidence)
        if not items:
            raise IntelligenceContractError("intelligence records require evidence")
        type_name = record_type.strip().lower().replace(" ", "_")
        source_name = source.strip()
        subject_name = subject_type.strip().lower().replace(" ", "_")
        subject_value = str(subject_id).strip()
        reason = rationale.strip()
        if not all((type_name, source_name, subject_name, subject_value, reason)):
            raise IntelligenceContractError("record type, source, subject and rationale are required")

        now = _as_utc(now_utc) if now_utc is not None else _utc_now()
        confidence = evidence_confidence(
            items,
            half_life_seconds=half_life_seconds,
            now_utc=now,
        )
        freshness = max(
            freshness_score(
                item.observed_at_utc,
                half_life_seconds=half_life_seconds,
                now_utc=now,
            )
            for item in items
        )
        return cls(
            kind=normalized_kind,
            record_type=type_name,
            source=source_name,
            subject_type=subject_name,
            subject_id=subject_value,
            rationale=reason,
            evidence=items,
            confidence=confidence,
            freshness=clamp01(freshness),
            created_at_utc=now.isoformat(),
            attributes=dict(attributes or {}),
        )

    @property
    def event_type(self) -> str:
        return f"intelligence.{self.kind.value}.{self.record_type}"

    def event_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "record_type": self.record_type,
            "confidence": self.confidence,
            "freshness": self.freshness,
            "rationale": self.rationale,
            "attributes": dict(self.attributes),
            "intelligence_schema_version": self.schema_version,
        }

    def event_evidence(self) -> dict[str, Any]:
        return {
            "items": [item.as_dict() for item in self.evidence],
            "confidence_model": "importance_weighted_mean(observation_confidence*source_trust*freshness)",
        }
