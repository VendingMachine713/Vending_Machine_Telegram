# VM Brain Canonical Recommendation Lifecycle

## Purpose

Canonical review recommendations now have a governed metadata lifecycle so obsolete proposals do not remain indefinitely actionable in operator views.

This lifecycle applies only to `PROPOSED` canonical relationship re-engagement review recommendations. Accepted recommendations are never automatically expired.

## Expiry conditions

A proposal may transition to `EXPIRED` when its supporting canonical inference is:

- older than the configured freshness window (72 hours by default);
- superseded by newer evidence with a different support signature;
- newly suppressed by current canonical risk evidence;
- below the configured opportunity threshold;
- missing or invalid in a way that breaks its canonical provenance.

## Governance

`PROPOSED -> EXPIRED` and `BLOCKED -> EXPIRED` are governed metadata transitions. `EXPIRED` remains terminal.

`ACCEPTED -> EXPIRED` is intentionally forbidden. Once an operator accepts a recommendation, automatic lifecycle cleanup cannot override that decision.

Each expiry uses the existing `transition_recommendation()` path, so state change and `recommendation.expired` audit event are committed together.

## Safety boundary

Expiry is metadata cleanup only. It does not:

- accept a recommendation;
- complete a recommendation;
- send Telegram messages;
- schedule work;
- execute bot actions;
- grant external action authority.

Mission Control exposes lifecycle counts, including expired canonical review recommendations, while automatic acceptance and execution remain disabled.