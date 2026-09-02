# VM Brain Phase 1 — Make Brain Trustworthy

Phase 1 advances VM Core from governed calibration v1.7 to the passive VM Brain v2.0 decision layer.

## v1.8 — Rule Health and Post-Activation Monitoring

Module: `shared.vm_core.rule_health`

- evaluates only ACTIVE governed rule versions
- measures outcomes recorded after activation
- requires a minimum sample before judging health
- compares current confidence-weighted outcome value with pre-activation baseline when available
- respects the deterministic staged-rollout cohort from v1.7 so control subjects are not misattributed to a partial rollout
- reports post-activation outcomes seen, included and excluded from the active cohort
- classifies rules as `INSUFFICIENT_DATA`, `STABLE`, `IMPROVING` or `DEGRADED`
- emits rollback recommendations for degraded rules
- never performs automatic rollback

A 10% rollout is therefore judged only on subjects inside that deterministic 10% cohort. Outcomes from the remaining 90% do not make the changed rule look better or worse.

## v1.9 — Confidence and Evidence Hardening

Module: `shared.vm_core.confidence`

Recommendation confidence, verification confidence and evidence quality remain separate values. Missing verification does not inherit recommendation confidence, preventing a recommendation from validating itself.

The trust view also tracks:

- structural evidence quality
- evidence freshness / time decay
- explicit source reliability when supplied
- whether independent verification is actually available
- conservative calibrated confidence

The calibrated confidence is deliberately conservative so high recommendation confidence cannot hide weak verification, stale evidence or weak evidence quality. No confidence calculation grants execution authority.

## v2.0 — Passive Decision Engine

Module: `shared.vm_core.decision_engine`

The decision engine ranks PROPOSED recommendations using bounded components:

- governed priority and staged rule delta
- urgency
- opportunity
- estimated value
- calibrated confidence
- risk
- effort
- active rule health

It also performs passive duplicate suppression and identifies conflicting recommendations for the same subject. Conflicts are surfaced for human resolution; they are never automatically resolved.

The decision engine does not accept recommendations, execute Telegram actions, mutate Smart Auto Poster queues or modify bot-owned state.

## Operator view

```powershell
python tools/vm_brain_phase1.py summary
python tools/vm_brain_phase1.py health
python tools/vm_brain_phase1.py decisions --limit 20
```

## Safety invariants

- automatic rollback: disabled
- automatic conflict resolution: disabled
- automatic recommendation acceptance: disabled
- automatic execution: disabled
- external action authority: disabled
- Smart Auto Poster uncertain retry policy: unchanged
- Telegram sending authority: unchanged

## Validation expectations

Phase 1 tests cover:

- minimum sample requirements
- degraded-rule rollback recommendations without automatic rollback
- staged-rollout cohort attribution
- independent recommendation and verification confidence
- freshness and source-reliability signals
- missing-verification behaviour
- passive decision ranking
- duplicate suppression and conflict surfacing
- preservation of PROPOSED recommendation state
- absence of external action authority

The Phase 1 progression is:

`Observe -> Correlate -> Recommend -> Govern -> Verify -> Learn -> Calibrate -> Governed Change -> Monitor -> Calibrate Confidence -> Rank Decisions`

The next phase can add Mission Control and richer cross-bot entity/context views without weakening these boundaries.
