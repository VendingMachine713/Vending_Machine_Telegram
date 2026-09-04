# VM Brain Canonical Signal Bridge and Correlation

Status: Trust Layer milestone 1.4

## Purpose

This milestone begins the real migration from legacy VM intelligence projections to
the canonical Trust Layer without breaking existing consumers.

The legacy `intelligence_signals` table remains in place. Selected signals are read
from that table and published in parallel as canonical `IntelligenceRecord` events.

## First migrated signals

The initial bridge intentionally supports only three established chat-level signals:

- `relationship_dormant_presence` from VM Relationship Manager
- `relationship_cooling_presence` from VM Relationship Manager
- `search_activity_spike` from Universal Search

Unsupported signal types and non-chat subjects fail closed.

## Privacy and identity

Raw Telegram chat IDs are replaced by the canonical hashed chat identity from
`canonical_entity_id()` before canonical publication.

Relationship evidence is allow-listed. Raw contact IDs and the legacy signal key are
not copied into canonical payloads. The legacy key is represented only by a one-way
reference hash used for traceability/deduplication.

## Parallel migration and deduplication

The bridge does not mutate or delete legacy signals.

Each supported legacy signal gets a semantic signature based on its meaningful
state. Repeated bridge passes do not append a new canonical event when the legacy
signal is unchanged.

## First cross-bot inference

`canonical_correlation.correlate_relationship_search()` matches only:

- canonical Relationship Manager relationship-presence signals;
- canonical Universal Search activity-spike signals;
- the same canonical chat subject.

The result is an `INFERENCE` named `relationship_reengagement_opportunity`.

Its two supporting evidence items point to durable canonical event IDs. Their
provenance is verified against the VM event ledger before the inference is
published.

A spoofed relationship event from another source is ignored.

## Confidence

Source trust is applied when the legacy signal is first bridged into its canonical
signal. When one canonical signal is later used as evidence for the cross-bot
inference, its already-calculated canonical confidence is used directly so source
trust is not accidentally applied twice.

## Safety boundary

This milestone creates:

`legacy signal -> canonical signal -> cross-bot inference`

It does not create:

`recommendation -> decision -> action`

`run_canonical_brain_pass()` explicitly reports `recommendations_created = 0` and
`automatic_execution = false`.

No Telegram message, campaign mutation, relationship mutation, retry, outreach, or
autonomous action is available through this path.

## Next milestone

After CI and shadow validation are green:

1. add VM Guard canonical risk evidence to the same chat correlation;
2. suppress or downgrade opportunity inference when Guard risk is elevated;
3. shadow-compare canonical opportunity results with the established legacy
   `relationship_activity_opportunity` path;
4. only then consider generating a canonical recommendation, still requiring
   governance and no automatic execution.
