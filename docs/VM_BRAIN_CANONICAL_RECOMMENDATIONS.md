# VM Brain Canonical Recommendations

## Purpose

This milestone introduces the first canonical recommendation constructor after the shadow, parity, freshness and calibration-readiness gates.

The constructor creates **operator-review metadata only**. It does not accept recommendations, schedule work, send Telegram messages or grant an executor action authority.

## Promotion requirements

Canonical review recommendations are constructed only when `canonical_recommendation_readiness()` reports `READY_FOR_GOVERNED_DEVELOPMENT`.

That gate already checks:

- minimum canonical subject coverage;
- legacy/canonical parity;
- suppression policy;
- fresh canonical evidence;
- calibration review holds once enough verified outcomes exist.

If readiness is not satisfied, the constructor performs no recommendation writes.

## Individual inference requirements

For each latest canonical relationship re-engagement inference:

- the inference must not be suppressed;
- opportunity score must meet the configurable threshold (60 by default);
- confidence and support signature must be valid;
- the recommendation is created as `PROPOSED` only;
- action text is explicitly an operator review instruction.

Suppressed inferences are never promoted into review recommendations.

## Idempotency and provenance

Recommendation keys are derived from canonical subject ID plus the inference support signature. Re-running the constructor with unchanged evidence refreshes the existing proposal instead of duplicating it.

Each newly created proposal emits a `recommendation.proposed` audit event linked to:

- canonical inference event ID;
- support signature;
- rule ID and rule version;
- recommendation correlation ID.

## Risk handling

If recent VM Guard evidence exists, its risk score is carried into the recommendation evidence. If Guard risk has not been assessed recently, risk defaults to 50 rather than being treated as zero risk.

## Governance boundary

The following remain false:

- automatic acceptance;
- automatic execution;
- external action authority.

Any later state transition still goes through the existing recommendation governance layer. This milestone does not add a Telegram executor.