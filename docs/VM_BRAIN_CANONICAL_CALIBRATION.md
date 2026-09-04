# VM Brain Canonical Inference Outcomes and Calibration

## Purpose

This layer lets VM Brain attach verified outcomes to canonical shadow inferences and evaluate whether the inference confidence is calibrated against real results.

It is deliberately separate from the existing recommendation learning system. Canonical inference outcomes can therefore be collected while the canonical path remains in shadow mode and before any governed recommendation constructor exists.

## Outcome contract

`record_canonical_inference_outcome(...)` records an `intelligence.outcome.relationship_reengagement_opportunity` event that:

- references one existing canonical inference event;
- verifies that inference through the Trust Layer provenance checks;
- accepts `POSITIVE`, `NEUTRAL`, `NEGATIVE`, or `UNKNOWN`;
- stores bounded value/confidence and an actor label;
- rejects duplicate outcomes for the same inference;
- never changes rules, thresholds, recommendations or Telegram state.

## Calibration

Only verified `POSITIVE` and `NEGATIVE` outcomes are used for binary calibration metrics. `NEUTRAL` and `UNKNOWN` remain visible as outcome events but do not distort the binary score.

The passive report includes:

- known binary outcome count;
- positive and negative counts;
- positive rate;
- average predicted inference confidence;
- calibration gap;
- Brier score.

At least eight known binary outcomes are required before the status moves beyond `INSUFFICIENT_DATA`.

Possible statuses are:

- `INSUFFICIENT_DATA`
- `WELL_CALIBRATED`
- `ACCEPTABLE`
- `REVIEW_REQUIRED`

These statuses are advisory only. `REVIEW_REQUIRED` does not automatically modify any rule, confidence model or source trust setting.

## Operator visibility

Mission Control exposes `headline.canonical_calibration`. A `REVIEW_REQUIRED` result also sets `attention.canonical_calibration_review_required`.

## Safety boundary

The following remain false:

- automatic rule change;
- automatic recommendation creation;
- automatic recommendation approval;
- automatic execution;
- external action authority.

Calibration evidence is intended to support a later governed decision about whether canonical recommendation development should advance. It does not itself grant that authority.
