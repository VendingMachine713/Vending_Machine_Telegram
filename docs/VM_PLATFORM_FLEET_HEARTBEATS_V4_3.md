# VM Platform v4.3 — Fleet Heartbeats and Passive Incident Synthesis

## Purpose

v4.3 closes the gap between having a heartbeat schema and having dependable fleet-wide heartbeat publication.

The five active VM services already enter VM Core through `BotEventPublisher.started()`. v4.3 makes that shared lifecycle hook establish a standard durable heartbeat lease automatically, so individual bots do not need separate timers or bespoke heartbeat implementations.

## Standard heartbeat lease

`BotEventPublisher.started()` now:

1. records an immediate durable service heartbeat;
2. starts one failure-isolated daemon heartbeat loop;
3. refreshes the durable heartbeat every 45 seconds;
4. avoids emitting a general telemetry event for every periodic refresh;
5. remains idempotent if the heartbeat loop is requested more than once.

`BotEventPublisher.stopped()` stops the heartbeat lease before publishing the existing stop event.

Telemetry failures remain isolated from bot business logic.

## Fleet coverage

`shared.vm_core.fleet_heartbeat.fleet_heartbeat_snapshot()` distinguishes two different forms of coverage:

- **integration coverage** — whether each adapter-backed service entrypoint uses `BotEventPublisher` and its shared `publisher.started()` lifecycle hook;
- **observed coverage** — whether a durable heartbeat has actually been observed for that service in the platform database.

The CI gate requires 100% integration coverage for the five active services:

- `Universal_Search`
- `VM_Guard`
- `Admin_Command_Centre`
- `VM_Relationship_Manager`
- `Smart_Auto_Poster_V2`

Observed coverage is runtime evidence and is not expected to be 100% in a clean CI checkout.

## Telemetry contract v2

The service telemetry read model now also exposes:

- `runtime_updated_at_utc`
- `runtime_age_seconds`

This enables the platform to distinguish a newly recorded RUNNING service from one that has remained RUNNING for long enough that a missing heartbeat is meaningful.

## Passive incident synthesis

The fleet heartbeat layer synthesizes read-only incident candidates for:

- stale heartbeat while runtime is recorded RUNNING;
- invalid heartbeat timestamp/evidence while runtime is recorded RUNNING;
- missing heartbeat after the RUNNING runtime state itself has remained old enough to cross the stale threshold.

These candidates include a stable incident key, service subject, severity, summary, and bounded evidence metadata.

They are **not persisted automatically** by Mission Control and they grant no recovery authority. This keeps observation and action governance separate.

## Mission Control

Mission Control remains contract v4 and advances to platform revision 3. It adds:

- fleet heartbeat status;
- expected/integrated service counts;
- integration coverage percentage;
- observed heartbeat coverage percentage;
- synthesized incident-candidate count;
- incident-candidate details under operator attention;
- the complete read-only fleet heartbeat envelope under `platform.fleet_heartbeat`.

Existing canonical Opportunity Engine, Relationship Intelligence, Group/Search Intelligence, trust, review governance, telemetry, registry, adapters, health, and incident intelligence remain additive and unchanged in authority.

## Safety boundary

v4.3 does **not** enable:

- automatic restart;
- automatic incident execution;
- automatic recommendation acceptance;
- Telegram execution;
- automatic threshold/rule changes;
- external action authority.

The lifecycle heartbeat itself writes only VM Core observability state. Incident synthesis remains read-only and operator-facing.

## Next low-risk milestone

A suitable follow-on is a governed operational incident lifecycle that can explicitly open/refresh/resolve heartbeat incidents from these candidates under a separate operator-controlled cycle. Automatic restart should remain disabled until recovery policy, cooldown, idempotency, and verification gates are reviewed independently.
