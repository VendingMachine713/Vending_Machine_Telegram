# VM Brain Decision Engine v2

## Purpose

Decision Engine v2 evolves the existing shared decision module in place. It preserves the legacy governed-recommendation ranking API while adding a canonical operator-review path over the newer Brain chain:

`Relationship + Group/Search + Posting -> Opportunity -> Risk Fusion -> Predictions -> Decision Engine`

The canonical Decision Engine ranks what deserves operator attention. It does not execute the resulting choice.

## Canonical dispositions

Each prediction is converted into one explicit operator disposition:

- `RISK_REVIEW_FIRST` — explicit fused risk requires operator review before value review
- `PRIORITISE_OPERATOR_REVIEW` — strong forecast with a sufficiently strong lower uncertainty bound
- `REVIEW_WHEN_AVAILABLE` — moderate expected value
- `DEFER_LOW_EXPECTED_VALUE` — weak current forecast; retained rather than deleted

Risk-review items surface first so safety evidence cannot be hidden behind a high value score.

## Scoring

The diagnostic decision score combines:

- forecast probability
- forecast lower bound
- source confidence
- fused risk penalty

The original upstream evidence remains visible alongside the score. Fixed code thresholds are used for this milestone; the Decision Engine does not tune them automatically.

## Backwards compatibility

`ranked_decisions()` and the existing legacy `decision_summary()` fields remain available. New canonical fields are additive:

- `canonical_decision_count`
- `canonical_top_decisions`
- `canonical_disposition_counts`
- `canonical_decisions_read_only`

Mission Control exposes both legacy and canonical decision surfaces.

## Identity boundary

Canonical decisions use only upstream canonical subject identifiers. Raw Telegram IDs/contact IDs are not introduced or exposed.

## Safety boundary

A canonical decision is an advisory operator-review priority, not an instruction with action authority. The layer does not:

- create or accept recommendations
- resolve conflicts automatically
- execute Telegram or external actions
- mutate Smart Auto Poster queues/destinations
- suppress candidates silently
- change thresholds or rules automatically
- grant external action authority

All canonical decisions set `requires_human_review=true`, `decision_is_advisory=true`, and the automatic authority flags to false.
