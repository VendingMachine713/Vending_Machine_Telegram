# VM Brain — Relationship Intelligence

## Purpose

Relationship Intelligence is the first domain intelligence layer above the shared VM Brain trust foundation.

It does not add decision logic to `VM_Relationship_Manager`. Instead, Relationship Manager remains a producer of observations/signals and VM Brain builds the unified relationship view. This preserves the platform rule that lower-level bots feed one shared Brain rather than growing isolated intelligence frameworks.

## Inputs

The read model consumes existing canonical Relationship Manager events from the shared event ledger:

- `intelligence.signal.relationship_dormant_presence`
- `intelligence.signal.relationship_cooling_presence`
- `intelligence.signal.business_reload_opportunity`
- `intelligence.signal.business_dormant_client_opportunity`

Only canonical Telegram chat IDs are accepted at the Brain boundary. Raw/native subject identifiers are ignored and never returned through this surface.

## Unified profile

`relationship_intelligence_summary()` groups the latest supported signal of each type by canonical subject and exposes one concise profile containing:

- canonical subject ID
- current relationship state
- relationship/lifecycle type where available
- relationship and trust scores
- inactivity/overdue indicators
- group interaction and transaction counts
- business signal flags
- evidence event IDs and evidence count
- mean signal confidence
- latest evidence time
- deterministic relationship attention score

The attention score is explicitly **diagnostic only**. It helps operators and future shared Brain layers prioritise which relationship records deserve inspection; it is not an Opportunity Engine score, recommendation, decision, or execution permission.

## State precedence

When multiple current signals exist for one canonical subject, the read model uses the following display precedence:

1. `DORMANT`
2. `COOLING`
3. `DORMANT_CLIENT`
4. `BUSINESS_ACTIVE`
5. `OBSERVED`

All current signal flags remain visible even when a higher-precedence relationship state is selected.

## Evidence handling

For duplicate/repeated observations, only the latest event for each supported signal type contributes to the current profile. This makes repeated reads idempotent and prevents stale duplicates from inflating current evidence.

Malformed payloads are skipped and reported. Unsupported Relationship Manager event types do not enter the profile model.

## Mission Control

Mission Control v4 exposes:

- Relationship Intelligence status
- relationship profile count
- dormant/cooling counts
- ranked diagnostic relationship profiles under operator attention
- malformed-event count
- non-canonical events ignored
- full passive `relationship_intelligence` summary

The Platform Foundation v4 envelope remains unchanged and authoritative.

## Safety invariants

Relationship Intelligence is read-only and grants no action authority:

- no recommendation is created
- no automatic acceptance
- no Telegram/external execution
- no automatic rule or threshold changes
- no external action authority

The next roadmap layers may consume this shared read model, but they must preserve governance boundaries and canonical IDs.
