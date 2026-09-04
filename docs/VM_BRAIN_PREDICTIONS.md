# VM Brain Predictions

## Purpose

Predictions is a passive forecasting layer over the existing canonical intelligence chain:

`Relationship + Group/Search + Posting + Risk -> risk-adjusted opportunity -> Prediction -> later Decision Engine`

It estimates the probability that an operator-review candidate will produce positive verified value over a fixed 48-hour review horizon. It does not create recommendations or actions.

## Forecast method

This milestone deliberately uses a transparent baseline rather than pretending a trained model exists.

The starting signal is the risk-adjusted canonical opportunity score. Source confidence moderates the estimate toward neutral when evidence is uncertain.

When the existing canonical review calibration layer has at least eight known binary verified outcomes, Predictions may blend the observed positive outcome rate into the baseline:

- 70% confidence-adjusted opportunity heuristic
- 30% verified positive-outcome base rate

Below that sample threshold, outcome history is not used in the probability calculation.

Each forecast clearly reports its method:

- `HEURISTIC_BASELINE`
- `HEURISTIC_PLUS_VERIFIED_OUTCOME_BASE_RATE`

`trained_model` remains `false`.

## Uncertainty

Every prediction includes a bounded interval. Lower-confidence source evidence produces a wider interval so Mission Control does not present a point estimate with false precision.

Fields include probability, lower/upper bounds, source confidence, original and risk-adjusted opportunity scores, risk level, calibration status, verified outcome count, and whether the empirical base rate was used.

## Identity boundary

Predictions operate only on canonical subject identifiers supplied by upstream Brain layers. They do not read or expose raw Telegram/contact identifiers.

## Mission Control

Mission Control exposes prediction status/count, the verified-outcome sample size, whether empirical history was used, and operator-facing probability/uncertainty estimates. VM Platform v4.3 fleet heartbeat and telemetry revision-3 surfaces remain preserved.

## Safety boundary

Predictions are advisory and read-only. They do not create/accept recommendations, execute Telegram or external actions, suppress candidates, mutate Smart Auto Poster state, modify trust weights, tune thresholds/rules, train/deploy a model automatically, or grant external action authority.
