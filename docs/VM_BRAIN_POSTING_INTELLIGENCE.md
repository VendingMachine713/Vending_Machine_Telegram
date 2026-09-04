# VM Brain Posting Intelligence

## Purpose

Posting Intelligence is the Brain-level, read-only operational view of Smart Auto Poster delivery state.

It sits above the bot rather than moving posting logic into VM Brain:

`Smart Auto Poster state -> Posting Intelligence -> Opportunity/Risk/Decision layers`

Smart Auto Poster remains the owner of its queue, campaign, destination, account, retry, reconciliation and Telegram execution behaviour.

## Current inputs

The projection reads the Smart Auto Poster SQLite database in read-only mode and uses explicit state from:

- `destinations`
- `queue`
- `campaigns` when present

It derives per-destination operational evidence including:

- enabled/review/quarantine state
- recent successful and failed deliveries
- unresolved `UNCERTAIN` queue items
- active queue depth
- recent delivery success rate
- campaign diversity count
- latest queue activity
- last-post and next-eligible timestamps
- deterministic diagnostic posting-readiness score

## Identity and privacy boundary

Raw Telegram destination IDs never leave the projection. Each group ID is converted through the shared VM Brain canonical identity contract before it is returned:

`telegram:chat:<24-character digest>`

The projection does not return message content, usernames, account identities, session paths or Telegram user IDs.

## Safety boundary

Posting Intelligence is diagnostic only. It does not:

- insert/update queue rows
- enable or disable destinations/campaigns
- retry uncertain deliveries
- create recommendations
- accept recommendations
- send Telegram messages
- change thresholds or rules
- grant external action authority

The output carries these invariants explicitly so downstream consumers cannot mistake a readiness score for execution authority.

## Delivery health

Destination delivery health is conservative:

- `ATTENTION` when unresolved uncertain delivery exists
- `DEGRADED` when recent failures materially reduce resolved-delivery success
- `HEALTHY` when explicit recent resolved evidence is healthy
- `NO_HISTORY` when there is no resolved recent delivery evidence

Absence of delivery evidence is never interpreted as successful delivery.

## Mission Control

Mission Control v4.2 exposes:

- Posting Intelligence status
- destination count
- attention destination count
- unresolved uncertain queue count
- canonical destination profiles requiring attention
- malformed-row count

The Platform v4.2 telemetry, registry, adapter and health surfaces remain unchanged.

## Roadmap boundary

This milestone intentionally stops before Risk Fusion. Posting delivery health can be consumed by the next Risk Fusion milestone, but it does not yet suppress or alter canonical opportunity scores automatically.
