from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_contracts import (
    EvidenceRef,
    IntelligenceContractError,
    IntelligenceKind,
    IntelligenceRecord,
    evidence_confidence,
    freshness_score,
)
from shared.vm_core.publisher import BotEventPublisher


NOW = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def _evidence(*, hours_old: float = 0, confidence: float = 1.0,
              source_trust: float = 1.0, importance: float = 1.0,
              source: str = "VM_Relationship_Manager") -> EvidenceRef:
    observed = NOW - timedelta(hours=hours_old)
    return EvidenceRef(
        source=source,
        observed_at_utc=observed.isoformat(),
        confidence=confidence,
        source_trust=source_trust,
        importance=importance,
        event_id=17,
        reference="message:17",
    )


def test_freshness_is_one_at_observation_and_half_after_one_half_life():
    assert freshness_score(NOW, half_life_seconds=3600, now_utc=NOW) == pytest.approx(1.0)
    assert freshness_score(
        NOW - timedelta(hours=1),
        half_life_seconds=3600,
        now_utc=NOW,
    ) == pytest.approx(0.5)


def test_future_evidence_cannot_inflate_freshness():
    assert freshness_score(
        NOW + timedelta(minutes=5),
        half_life_seconds=3600,
        now_utc=NOW,
    ) == pytest.approx(1.0)


def test_evidence_confidence_is_explainable_weighted_mean():
    current = _evidence(confidence=0.8, source_trust=0.5, importance=3)
    stale = _evidence(hours_old=1, confidence=1.0, source_trust=1.0, importance=1)
    # current effective confidence = .4; stale = .5 after one half-life
    # weighted mean = ((.4 * 3) + (.5 * 1)) / 4 = .425
    result = evidence_confidence(
        [current, stale],
        half_life_seconds=3600,
        now_utc=NOW,
    )
    assert result == pytest.approx(0.425)


def test_contract_rejects_untraceable_or_invalid_evidence():
    with pytest.raises(IntelligenceContractError):
        EvidenceRef(source="", observed_at_utc=NOW.isoformat())
    with pytest.raises(IntelligenceContractError):
        EvidenceRef(source="bot", observed_at_utc="not-a-time")
    with pytest.raises(IntelligenceContractError):
        IntelligenceRecord.from_evidence(
            kind=IntelligenceKind.SIGNAL,
            record_type="engagement_rise",
            source="VM_Relationship_Manager",
            subject_type="contact",
            subject_id="123",
            rationale="Observed activity increased",
            evidence=[],
            half_life_seconds=3600,
            now_utc=NOW,
        )


def test_record_separates_kind_from_domain_type_and_calculates_confidence():
    record = IntelligenceRecord.from_evidence(
        kind=IntelligenceKind.INFERENCE,
        record_type="reengagement_opportunity",
        source="VM_Relationship_Manager",
        subject_type="contact",
        subject_id=123,
        rationale="Activity resumed after dormancy",
        evidence=[_evidence(confidence=0.9, source_trust=0.8)],
        half_life_seconds=86400,
        now_utc=NOW,
        attributes={"trend": "rising"},
    )
    assert record.event_type == "intelligence.inference.reengagement_opportunity"
    assert record.subject_id == "123"
    assert record.confidence == pytest.approx(0.72)
    assert record.freshness == pytest.approx(1.0)
    assert record.event_payload()["intelligence_schema_version"] == 1
    assert record.event_evidence()["items"][0]["event_id"] == 17


def test_publisher_persists_canonical_intelligence_event(tmp_path: Path):
    record = IntelligenceRecord.from_evidence(
        kind=IntelligenceKind.SIGNAL,
        record_type="relationship_activity_change",
        source="VM_Relationship_Manager",
        subject_type="contact",
        subject_id="123",
        rationale="Recent interaction rate exceeds baseline",
        evidence=[_evidence()],
        half_life_seconds=86400,
        now_utc=NOW,
    )
    publisher = BotEventPublisher("VM_Relationship_Manager", tmp_path, instance_id="test-instance")
    event_id = publisher.intelligence(record)

    assert event_id is not None
    db = PlatformDB(root=tmp_path)
    rows = db.events(limit=1)
    assert len(rows) == 1
    row = rows[0]
    assert row["event_type"] == "intelligence.signal.relationship_activity_change"
    assert row["subject_type"] == "contact"
    assert row["subject_id"] == "123"
    assert row["correlation_id"] == "brain:signal:contact:123"
    payload = json.loads(row["payload_json"])
    evidence = json.loads(row["evidence_json"])
    assert payload["confidence"] == pytest.approx(1.0)
    assert payload["freshness"] == pytest.approx(1.0)
    assert evidence["items"][0]["source"] == "VM_Relationship_Manager"


def test_publisher_fails_closed_on_source_mismatch(tmp_path: Path):
    db = PlatformDB(root=tmp_path)
    db.init()
    record = IntelligenceRecord.from_evidence(
        kind=IntelligenceKind.FACT,
        record_type="activity_observed",
        source="Universal_Search",
        subject_type="group",
        subject_id="99",
        rationale="Message activity observed",
        evidence=[_evidence(source="Universal_Search")],
        half_life_seconds=86400,
        now_utc=NOW,
    )
    publisher = BotEventPublisher("VM_Relationship_Manager", tmp_path)
    assert publisher.intelligence(record) is None
    assert "source does not match" in (publisher.last_error or "")
    assert db.events(limit=10) == []
