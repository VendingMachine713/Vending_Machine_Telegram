# VM Brain — Opportunity Engine v2

## Purpose

Opportunity Engine v2 evolves the existing `shared.vm_core.opportunity_intelligence` module in place. It preserves the legacy signal-table opportunity API for compatibility while adding a canonical shared-Brain opportunity view based on the new Relationship Intelligence and Group/Search Intelligence layers.

No parallel opportunity framework is introduced.

## Canonical inputs

`canonical_opportunities()` consumes the existing passive shared read models:

- Relationship Intelligence
- Group/Search Intelligence

The join key is the canonical Telegram chat ID only. Raw Telegram/contact IDs are not introduced into the canonical opportunity surface.

## Opportunity candidate types

Current deterministic candidate classifications are:

- `REENGAGEMENT_ACTIVITY_REVIEW`
- `DORMANT_RELATIONSHIP_REVIEW`
- `COOLING_ACTIVITY_REVIEW`
- `BUSINESS_RELOAD_REVIEW`
- `DORMANT_CLIENT_REVIEW`
- `RELATIONSHIP_REVIEW`

These are operator-facing diagnostic candidate categories, not executable actions.

## Scoring

The canonical score combines:

- Relationship Intelligence diagnostic attention
- Group/Search diagnostic momentum when the same canonical subject has cross-domain evidence
- a bounded business-signal bonus for reload/dormant-client evidence
- a bounded cross-domain corroboration bonus

The score is deterministic and capped at 100. Confidence is the mean of available source-layer confidence values.

Each candidate carries the contributing event IDs so later governance, audit and decision layers can trace evidence without copying arbitrary payloads.

## Backwards compatibility

The existing `opportunities()` function and legacy `opportunity_summary()` fields remain available:

- `count`
- `blocked_count`
- `top_opportunities`

The summary adds canonical fields:

- `canonical_count`
- `canonical_top_opportunities`
- `canonical_cross_domain_count`
- `canonical_risk_fusion_applied`
- `read_only_canonical_synthesis`

Mission Control v4.1 exposes both the legacy view and canonical opportunity candidates.

## Deliberate boundary before Risk Fusion

Opportunity Engine v2 does **not** apply Guard/incident risk fusion to canonical candidates. Every canonical candidate explicitly reports `risk_fusion_applied: false`.

This avoids prematurely mixing roadmap stages. The dedicated Risk Fusion milestone can consume the canonical candidate set and apply shared risk evidence with its own tests and governance boundaries.

## Safety invariants

Canonical opportunity synthesis is passive and read-only:

- no event/recommendation writes
- no recommendation creation
- no automatic acceptance
- no automatic execution
- no automatic threshold changes
- no automatic rule changes
- no external action authority

Controlled autonomy remains a later roadmap phase.
