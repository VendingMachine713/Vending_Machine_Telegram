# VM Brain Canonical Promotion Gate v2

## Purpose

The canonical recommendation-development gate now considers not only sample count and legacy/canonical parity, but also evidence freshness and verified calibration once enough outcomes exist.

This remains a development-readiness gate. Passing it does not create, approve, schedule or execute a recommendation.

## Default requirements

A canonical path may report `READY_FOR_GOVERNED_DEVELOPMENT` only when:

- at least five distinct canonical inference subjects are present;
- legacy/canonical parity passes;
- the suppression ratio remains within policy;
- canonical inference evidence is not stale (72-hour default freshness window);
- if at least eight verified binary outcomes exist, calibration is not `REVIEW_REQUIRED`.

If any required condition fails, the state remains `SHADOW_EVIDENCE_REQUIRED` and an explicit reason is reported.

## Additional hold reasons

`canonical_evidence_stale`
: Enough inference subjects may exist, but the newest canonical evidence is older than the configured freshness window.

`canonical_calibration_review_required`
: Enough verified positive/negative outcomes exist to evaluate calibration and the confidence model is materially miscalibrated.

Calibration does not block promotion while there are fewer than the configured minimum verified outcomes; the system reports `INSUFFICIENT_DATA` instead of pretending the model is calibrated.

## Safety

The gate keeps the following false:

- recommendation execution enabled;
- automatic recommendation creation;
- automatic recommendation approval;
- automatic rule changes;
- automatic execution;
- external action authority.

The purpose is to prevent stale or demonstrably miscalibrated canonical intelligence from being promoted merely because a minimum sample count has been reached.
