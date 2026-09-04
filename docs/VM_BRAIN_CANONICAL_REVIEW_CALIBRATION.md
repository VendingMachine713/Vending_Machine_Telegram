# VM Brain Canonical Review Outcome Calibration

## Purpose

VM Brain now evaluates whether canonical review recommendations are actually useful after operators complete them and record verified outcomes.

This is separate from canonical **inference** calibration. Inference calibration asks whether the Brain's inferred confidence matches reality. Review calibration asks whether the confidence assigned to the later operator-review recommendation matches verified recommendation outcomes.

## Data source

The report joins canonical relationship review recommendations to their verified outcomes using the existing recommendation and learning stores.

The original recommendation confidence is treated as the predicted probability. The operator's confidence in recording the outcome is deliberately **not** used as the prediction being calibrated.

## Metrics

The passive report includes:

- total recorded outcome events;
- positive, negative, neutral and unknown outcome counts;
- known binary outcome count;
- positive rate;
- average original recommendation confidence;
- calibration gap;
- Brier score;
- average realised value score.

Neutral and unknown outcomes remain visible but do not enter the binary calibration denominator.

## Default states

Fewer than eight verified positive/negative outcomes:

`INSUFFICIENT_DATA`

At eight or more binary outcomes:

- `WELL_CALIBRATED` when Brier score is at most 0.15 and absolute calibration gap is at most 0.10;
- `ACCEPTABLE` when Brier score is at most 0.25 and absolute calibration gap is at most 0.20;
- `REVIEW_REQUIRED` otherwise.

## Read-only behavior

Standalone calibration evaluation opens the platform database in SQLite read-only mode. If the database or required tables do not exist, it returns `INSUFFICIENT_DATA` without creating state or running migrations.

## Operator visibility

Mission Control exposes:

- `headline.canonical_review_calibration`;
- `attention.canonical_review_calibration_review_required`;
- the full `canonical_review_calibration` report.

## Safety

Calibration is advisory. It does not:

- change the recommendation threshold automatically;
- alter rule weights automatically;
- mutate source trust;
- accept or complete recommendations;
- send Telegram messages;
- schedule actions;
- grant external action authority.

Any later threshold proposal must be a separate governed milestone backed by enough verified outcomes.