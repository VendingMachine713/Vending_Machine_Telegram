# VM Brain Learning / Feedback v2

## Purpose

This milestone extends the existing `learning.py` outcome store and canonical review calibration rather than creating a second learning framework.

The current feedback chain is:

`operator review -> completion -> verified outcome -> calibration -> learning readiness`

The new passive learning view answers two separate questions:

1. Do we have enough verified feedback to evaluate the existing canonical review system?
2. Do we have the historical data required to validly backtest the newer Predictions and Decision Engine layers?

## Verified outcome coverage

The read model reports:

- canonical recommendation count
- completed recommendation count
- recorded verified outcomes
- completed recommendations still missing outcomes
- completed-outcome coverage ratio
- positive / neutral / negative / unknown counts
- known binary outcome count
- existing canonical calibration status, gap, Brier score and positive rate

Missing verified outcomes are surfaced as operator review flags rather than filled in automatically.

## Prediction and decision backtesting

Predictions are currently recomputed from the live evidence chain. They are **not immutable historical records** of what the Brain predicted at decision time.

Therefore this milestone intentionally reports:

`NOT_READY_NO_IMMUTABLE_PREDICTION_SNAPSHOTS`

instead of fabricating historical prediction or decision accuracy.

If immutable prediction snapshot events appear in the future, the status changes to:

`SNAPSHOTS_PRESENT_BACKTEST_NOT_IMPLEMENTED`

until an explicit governed backtest implementation is built and reviewed.

## Learning review flags

The passive view may surface operator flags including:

- `COLLECT_MISSING_VERIFIED_OUTCOMES`
- `COLLECT_MORE_BINARY_OUTCOMES`
- `REVIEW_CALIBRATION`
- `DESIGN_IMMUTABLE_PREDICTION_SNAPSHOTS`

These are review prompts only. No parameter is changed automatically.

## Read-only boundary

The new learning-readiness query opens the shared database in SQLite `mode=ro` with `PRAGMA query_only=ON`. Missing database/tables fail closed and the query does not initialise or migrate state.

The existing explicit `record_outcome()` write path remains unchanged for verified operator outcomes.

## Safety boundary

Learning/Feedback v2 does not:

- train or deploy a model automatically
- change trust weights
- change opportunity/decision thresholds
- change governance rules
- accept recommendations
- execute Telegram or external actions
- infer missing outcomes
- grant external action authority

Learning informs operator review; it does not autonomously rewrite the Brain.
