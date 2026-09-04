# VM Brain Canonical Recommendation Lineage

## Purpose

When new canonical evidence replaces an expired review proposal, VM Brain now records explicit predecessor/replacement lineage instead of leaving two unrelated recommendation records.

This improves auditability without reopening or mutating terminal recommendations.

## Lineage behavior

A newly created canonical relationship re-engagement review checks for the newest `EXPIRED` canonical review concerning the same canonical chat subject.

If one exists, the replacement recommendation evidence records:

- `supersedes_recommendation_id`;
- `supersedes_recommendation_key`;
- `supersession_reason`.

A separate `recommendation.supersedes` audit event links the predecessor ID, replacement ID, replacement canonical inference event and support signature.

## Terminal integrity

The predecessor remains `EXPIRED`. VM Brain does not reopen it, rewrite its historical evidence or change the operator decision model.

The replacement starts as a new `PROPOSED` recommendation and continues through the existing governance state machine independently.

## Idempotency

Lineage is emitted only when a replacement recommendation is first created. Refreshing unchanged evidence does not create duplicate supersession events.

## Safety

Recommendation lineage is metadata only. It does not:

- accept a recommendation;
- execute a recommendation;
- send Telegram messages;
- schedule work;
- mutate source-trust values;
- grant external action authority.

Automatic acceptance and execution remain disabled.