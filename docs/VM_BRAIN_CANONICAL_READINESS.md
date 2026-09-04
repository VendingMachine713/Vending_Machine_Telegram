# VM Brain Canonical Readiness Gate

Status: Trust Layer milestone 1.6

## Purpose

The canonical Brain path now has enough infrastructure to produce provenance-backed,
Guard-aware cross-bot inference and compare that output with the established legacy
projection. This milestone adds a conservative readiness gate before canonical
recommendation development is allowed to begin.

The gate does not create recommendations and never grants execution authority.

## Default readiness requirements

`canonical_recommendation_readiness()` requires:

- legacy-vs-canonical parity to pass;
- at least five distinct canonical re-engagement inference subjects;
- suppression behavior to remain inside the configured policy budget.

The minimum sample threshold is intentionally small enough for early migration but
large enough to prevent a single successful example from being treated as proof of
readiness. It can be increased as real shadow evidence accumulates.

## Status values

- `SHADOW_EVIDENCE_REQUIRED` — remain in observation/shadow mode.
- `READY_FOR_GOVERNED_DEVELOPMENT` — enough evidence exists to begin developing a
  separately governed recommendation constructor.

Neither status means recommendations may execute.

## Operator surface

`canonical_operator_summary()` combines:

- canonical readiness;
- intelligence audit summary;
- whether operator attention is needed;
- the next recommended migration action.

The surface explicitly reports:

- `recommendation_execution_enabled = false`
- `automatic_execution = false`

## Safety invariants

- readiness evaluation is read-only;
- a missing database is not created;
- insufficient samples fail closed;
- parity mismatch fails closed;
- recommendation construction remains absent from this milestone;
- recommendation execution remains disabled regardless of readiness result.

## Next milestone

When real shadow evidence satisfies this gate:

1. build a canonical recommendation constructor as a separate governed layer;
2. require supporting inference IDs and parity/readiness evidence;
3. emit recommendations as proposed/review-only objects;
4. keep governance transitions explicit and audited;
5. keep execution authority disabled until a later, separately validated autonomy stage.
