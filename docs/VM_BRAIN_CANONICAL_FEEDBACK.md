# VM Brain Canonical Review Feedback

## Purpose

Canonical relationship review recommendations now have an explicit operator-governed path from review decision to verified outcome feedback.

This reuses the existing VM Core governance and learning stores rather than introducing a parallel state machine.

## Operator lifecycle

A canonical review may be moved explicitly through:

- `PROPOSED -> ACCEPTED`;
- `PROPOSED -> DISMISSED`;
- `ACCEPTED -> COMPLETED`;
- `ACCEPTED -> DISMISSED`.

Automatic expiry remains owned by the separate proposal lifecycle module. The feedback adapter does not expose `EXPIRED` as an operator feedback command.

## Verified outcomes

A canonical review outcome may be recorded only after the recommendation reaches `COMPLETED`.

Supported outcomes remain the shared learning contract:

- `POSITIVE`;
- `NEUTRAL`;
- `NEGATIVE`;
- `UNKNOWN`.

The outcome evidence preserves canonical provenance by carrying the original canonical inference event ID and support signature from the recommendation evidence.

Only one outcome is allowed for each completed recommendation.

## Operator visibility

Mission Control reports:

- canonical review outcome count;
- completed canonical reviews still awaiting an outcome;
- outcome type counts in the full canonical feedback summary.

## Safety

This workflow does not:

- accept or complete recommendations automatically;
- infer outcomes automatically;
- alter intelligence rules automatically;
- send Telegram messages;
- schedule actions;
- grant external action authority.

Operator transitions, verified outcome entry, rule calibration, and any future execution capability remain separate governed steps.