# VM Brain Guard-Aware Canonical Parity

Status: Trust Layer milestone 1.5

## Purpose

This milestone adds VM Guard risk to the canonical cross-bot evidence path and
introduces a passive parity gate against the established legacy relationship
opportunity projection.

The goal is migration confidence, not new action authority.

## Canonical Guard bridge

`guard_risk_elevated` is now bridged from the established shared signal table as a
canonical `VM_Guard` signal on the same hashed chat identity used by Relationship
Manager and Universal Search.

The bridge intentionally excludes message-level Guard evidence such as message IDs
and reason-code arrays from canonical payloads. The canonical record retains the
risk score, confidence, source, timing and hashed chat identity needed for cross-bot
reasoning without broadening sensitive evidence exposure.

## Opportunity parity semantics

During this migration stage, canonical opportunity inference requires:

- `relationship_dormant_presence` from VM Relationship Manager;
- `search_activity_spike` from Universal Search;
- the same canonical chat identity.

Cooling relationship signals continue to be bridged, but they are not yet promoted
to opportunity inference. This deliberately matches the established legacy
opportunity semantics while parity is being measured.

## Guard suppression

The latest canonical Guard risk on the same chat is included only when it is no
more than six hours old.

When recent Guard risk is at least 60/100:

- the inference is marked `suppressed=true`;
- opportunity score is capped at 40/100;
- Guard event ID is included as provenance-verified supporting evidence;
- the inference remains review-only;
- no recommendation or action is created.

Stale or different-chat Guard evidence does not suppress the opportunity.

## Legacy-canonical parity gate

`canonical_shadow.evaluate_legacy_canonical_parity()` compares active legacy
`relationship_activity_opportunity` projections with the latest canonical
`relationship_reengagement_opportunity` inference per canonical chat.

The comparison checks:

- missing canonical subjects;
- extra canonical subjects;
- suppression-state mismatches;
- opportunity-score differences beyond a configurable tolerance.

The legacy shared database is opened read-only. Missing databases are not created.

A result is either `PASS` or `REVIEW_REQUIRED`. A pass is only migration evidence;
it never grants recommendation or action authority.

## Safety invariants

- legacy projections remain intact;
- no bot-owned database is mutated;
- no Telegram action is available;
- no canonical recommendation is created;
- `automatic_execution` remains false;
- Guard evidence is source-bound to `VM_Guard`;
- relationship/search evidence remains source-bound to their canonical producers;
- all inference supporting events are provenance verified.

## Next milestone

After CI and parity tests are green:

1. expose canonical parity status in passive operator/Brain summaries;
2. collect shadow results over real historical/live evidence;
3. add explicit canonical recommendation construction only after parity is stable;
4. keep recommendation governance separate from execution authority;
5. begin outcome/calibration instrumentation for canonical inference quality.
