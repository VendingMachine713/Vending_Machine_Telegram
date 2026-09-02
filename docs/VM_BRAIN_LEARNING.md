# VM Brain Verification + Learning

VM Core v1.5.0 adds a safe feedback foundation after recommendation governance.

## Purpose

The learning layer records what happened after a recommendation was completed, then aggregates descriptive performance by rule ID and rule version. It exists to improve future decision quality without allowing VM Brain to silently rewrite its own rules or execute Telegram actions.

## Outcome contract

Outcomes are recorded only for recommendations in `COMPLETED` state. Each recommendation may have one verified outcome.

Supported outcome types:

- `POSITIVE`
- `NEUTRAL`
- `NEGATIVE`
- `UNKNOWN`

Each outcome stores:

- recommendation ID/key/type
- rule ID and rule version
- subject
- value score from -100 to +100
- confidence from 0 to 1
- operator/actor
- optional note and evidence
- UTC timestamp

An atomic `recommendation.outcome_recorded` audit event is written with the outcome.

## Rule performance

`shared.vm_core.learning.rule_performance()` aggregates historical outcomes by exact rule version and reports:

- outcome count
- positive/neutral/negative/unknown counts
- positive rate over known outcomes
- confidence-weighted value score
- whether the sample has reached the initial learning-readiness threshold of five known outcomes

These metrics are descriptive only. They do not alter recommendation scores, thresholds, rules, bot settings or execution authority.

## Operator tool

```powershell
python tools/vm_brain_learning.py summary
python tools/vm_brain_learning.py rules
python tools/vm_brain_learning.py outcomes
python tools/vm_brain_learning.py record "recommendation:relationship_activity:123" positive --value 70 --confidence 0.9 --actor admin --note "Useful supplier follow-up"
```

## Safety boundary

The learning layer explicitly keeps:

- `automatic_rule_change = False`
- `automatic_execution = False`

VM Brain may collect evidence about rule quality, but rule changes remain deliberate code/configuration changes subject to normal review and testing.

The progression is now:

`Observe -> Correlate -> Recommend -> Govern -> Governed Action -> Verify -> Learn`

The next safe stage is controlled calibration: use accumulated outcome statistics to generate proposed scoring/rule adjustments for human review, not automatic self-modification.
