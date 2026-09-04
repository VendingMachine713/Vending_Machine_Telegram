# VM Brain Trust Layer

Status: Foundation milestone 1

## Purpose

VM Brain must be able to explain what it knows, where the information came from,
how fresh it is, and how much confidence should be placed in it before later
recommendation or automation layers are allowed to act.

This milestone deliberately adds no autonomous Telegram actions.

## Canonical intelligence progression

VM Brain keeps observed information separate from derived information:

1. `fact` - directly observed information.
2. `signal` - deterministic feature or change derived from facts.
3. `inference` - an interpretation supported by evidence.
4. `prediction` - an expected future outcome.
5. `recommendation` - a proposed operator/system action.
6. `decision` - a governed choice about a recommendation.
7. `action` - execution of an approved decision.
8. `outcome` - measured result of an action.

No layer should present an inference as a fact.

## Evidence contract

Each evidence item records:

- producer/source
- observation timestamp
- optional platform event ID/reference
- observation confidence
- source trust
- relative importance
- optional structured attributes

Evidence without a source or timezone-aware observation timestamp is rejected.

## Freshness

Freshness uses deterministic exponential half-life decay:

`freshness = 0.5 ** (age_seconds / half_life_seconds)`

A current observation has freshness `1.0`. Evidence one configured half-life old
has freshness `0.5`. A future timestamp is treated as current and cannot inflate
freshness above `1.0`.

Half-life is selected by the intelligence producer/domain because useful lifetime
varies by evidence type. For example, service health may decay rapidly while a
stable relationship attribute may decay more slowly.

## Confidence

Record confidence is not accepted as an arbitrary caller-supplied number.

For each evidence item:

`effective = observation_confidence * source_trust * freshness`

Record confidence is the importance-weighted mean of those effective evidence
scores.

This simple model is intentionally explainable. Later calibration can compare
predicted confidence with actual outcomes and revise source-trust or domain
weights without changing historical evidence.

## Publishing

`BotEventPublisher.intelligence(record)` publishes canonical records into the
existing VM Core event store.

Events use:

- `intelligence.<kind>.<record_type>` as the event type
- normal VM Core subject metadata
- a deterministic Brain correlation key by kind/subject
- evidence details in `evidence_json`
- calculated confidence/freshness in `payload_json`

A producer cannot publish a canonical intelligence record claiming to originate
from a different service. Source mismatches fail closed and preserve the existing
publisher guarantee that telemetry failures do not crash useful bot work.

## Compatibility

The existing `BotEventPublisher.signal(...)` method remains available unchanged.
Bots can migrate incrementally to the stricter canonical contract rather than
requiring a coordinated rewrite.

## Next trust-layer milestones

1. Evidence provenance validation against stored event IDs.
2. Governed source-trust registry with safe defaults.
3. Entity resolution contract and canonical entity IDs.
4. Duplicate/contradictory evidence handling.
5. Intelligence audit/replay views.
6. Historical replay tests and shadow-mode evaluation.
7. Migrate selected bot signals to canonical intelligence publishing.

The Trust Layer must remain read-mostly, auditable and fail-safe before VM Brain
is permitted to increase automation authority.
