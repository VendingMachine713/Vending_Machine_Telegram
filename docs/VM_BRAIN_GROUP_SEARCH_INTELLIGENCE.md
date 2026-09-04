# VM Brain — Group/Search Intelligence

## Purpose

Group/Search Intelligence is the shared VM Brain view of indexed Telegram activity. Universal Search remains the producer and owner of indexed content; VM Brain consumes only canonical aggregate activity signals.

This keeps search/group intelligence top-down: lower-level indexing and signal collection remain inside Universal Search, while cross-domain reasoning is performed by the shared Brain.

## Inputs

The layer currently consumes:

- `intelligence.signal.search_activity_spike` from `Universal_Search`

The existing adapter derives these signals from aggregate counts only. Message text, usernames and query text do not enter the shared Brain signal contract.

## Group activity profile

`group_search_intelligence_summary()` returns one current profile per canonical Telegram chat using the latest supported activity-spike event:

- canonical subject ID
- evidence event ID/time
- source confidence
- recent 24-hour message count
- baseline daily message count
- activity ratio
- recent 24-hour ad count
- recent ad share
- source signal score
- diagnostic group momentum score

Only safe aggregate fields are admitted. Unknown payload attributes are discarded.

## Diagnostic momentum

The deterministic `group_momentum_score` combines activity acceleration, message volume and ad share to help operators and later shared intelligence layers understand where group activity is concentrated.

It is explicitly diagnostic. It is not the Opportunity Engine score, a recommendation, a posting decision, or execution authority.

## Idempotency and data quality

Repeated activity-spike events do not inflate the current profile: only the latest supported event per canonical subject is used.

Malformed events are skipped and reported. Raw/non-canonical subject IDs are ignored and never returned. Events from other sources or unsupported signal types do not enter the model.

## Mission Control

Mission Control v4.1 exposes:

- Group/Search Intelligence status
- current group activity profile count
- ranked diagnostic group profiles
- malformed event count
- non-canonical event count ignored
- full passive `group_search_intelligence` summary

VM Platform v4.1 service-adapter evidence remains intact and authoritative alongside this additive Brain surface.

## Safety invariants

The layer is passive and read-only:

- indexed content is not exposed
- no recommendation creation
- no automatic acceptance
- no automatic rule or threshold changes
- no Telegram/external execution
- no external action authority

The Opportunity Engine may later consume Relationship Intelligence and Group/Search Intelligence together, but governance and canonical identity boundaries remain mandatory.
