# VM Brain — Trust/Foundation Polish

## Purpose

This milestone hardens the shared VM Brain trust layer before Relationship, Group/Search and Opportunity Intelligence build on it.

The foundation remains deterministic, explainable and passive. No automatic trust adjustment, recommendation acceptance, threshold/rule changes, Telegram execution or external action authority is introduced.

## Passive provenance verification

`verify_evidence_provenance()` now reads the shared event ledger using SQLite `mode=ro` plus `PRAGMA query_only=ON`.

It does not call `PlatformDB.init()`, create a missing database, migrate schema or write WAL state. Missing/unreadable stores fail closed with explicit reasons:

- `event_store_unavailable`
- `events_table_missing`
- `event_store_read_error`
- `event_not_found`
- `source_mismatch`
- `external_reference_unverified`

Successful verification can return the stored event type and canonical subject ID when one is present, without exposing a raw native subject identifier.

## Canonical identity helpers

The shared trust module owns canonical ID validation:

- `canonical_entity_id(...)` hashes native IDs into stable non-secret identifiers.
- `canonical_entity_parts(...)` parses only the canonical `<namespace>:<entity_type>:<24-hex-digest>` shape.
- `is_canonical_entity_id(...)` provides a safe boolean validation path.

These helpers allow downstream intelligence layers to reject raw Telegram/contact IDs at shared Brain boundaries instead of implementing separate validators.

## Source trust inheritance

Explicit producers retain their existing governed trust weights. Namespaced VM Core producers such as `vm_core.learning` and `vm_core.canonical_recommendations` inherit the explicit `vm_core` trust weight instead of accidentally falling back to unknown-source trust.

Unknown producers still receive the conservative `DEFAULT_SOURCE_TRUST` value. No runtime process changes the registry automatically.

## Operator health

`trust_foundation_summary()` is a read-only health view over recent `intelligence.*` events. It reports:

- event-store availability
- canonical-subject event count
- non-canonical-subject event count
- subjectless event count
- canonical-subject coverage
- configured source trust registry
- explicit safety flags

Mission Control exposes this under `trust_foundation`, with headline canonical-subject coverage and an attention count for non-canonical intelligence subjects. This is diagnostic only; legacy/non-canonical events are not rewritten automatically.

## Safety invariants

The trust foundation explicitly keeps these disabled:

- automatic trust changes
- automatic rule changes
- automatic recommendation acceptance
- automatic execution
- external action authority

Later intelligence layers should consume these shared trust/canonical-ID helpers rather than adding bot-local trust logic.
