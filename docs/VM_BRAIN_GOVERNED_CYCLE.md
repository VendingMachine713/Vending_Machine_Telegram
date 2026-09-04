# VM Brain Governed Canonical Cycle

## Purpose

VM Brain now has two explicit bounded runtime entry points rather than silently changing the established shadow behavior.

`run_canonical_brain_pass()` remains the compatibility-safe shadow path. It bridges and correlates intelligence but creates no recommendations.

`run_governed_canonical_brain_pass()` layers governed review-metadata maintenance on top of the shadow pass.

## Governed cycle order

1. Project passive Business Memory signals.
2. Bridge selected legacy signals into canonical Trust Layer records.
3. Correlate relationship, search and recent Guard evidence.
4. Evaluate legacy/canonical parity.
5. Expire obsolete `PROPOSED` canonical review recommendations.
6. Run the canonical readiness gate.
7. Create or refresh eligible `PROPOSED` operator-review recommendations.
8. Return recommendation and lifecycle summaries.

Expiry runs before proposal construction so stale or superseded review metadata is cleaned up before current evidence is promoted.

## Backward compatibility

The original shadow entry point preserves its no-recommendation contract. Existing callers do not start creating recommendations merely because the governed cycle exists.

A caller must explicitly select `run_governed_canonical_brain_pass()` to enable review-metadata construction.

## Safety boundary

The governed cycle still does not:

- accept a recommendation;
- complete a recommendation;
- send a Telegram message;
- schedule a Telegram action;
- execute a bot action;
- grant external action authority.

It only manages canonical inference and governed recommendation metadata. `automatic_acceptance`, `automatic_execution`, and `external_action_authority` remain false.