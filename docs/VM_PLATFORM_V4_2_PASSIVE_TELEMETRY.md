# VM Platform v4.2 — Passive Operational Telemetry

VM Platform v4.2 adds a read-only operational telemetry layer above the universal service heartbeat registry introduced in the platform database.

The milestone does not change bot execution behaviour, start/stop policy, Telegram authority, or VM Brain decision authority.

## Scope

`shared.vm_core.service_telemetry` combines three existing passive sources:

1. service runtime records from `services`
2. latest service heartbeat records from `service_heartbeats`
3. v4.1 VM Core adapter metadata

No schema migration is required.

## Telemetry contract

The telemetry contract is version 1 and reports:

- overall telemetry status
- observation time
- freshness and stale thresholds
- total and running service counts
- fresh, late, stale, and missing heartbeat counts
- attention and late-service lists
- one normalized telemetry record per known service

Each service record includes:

- service name
- recorded runtime status
- whether a PID is known
- adapter support and adapter ID
- whether a heartbeat is expected
- heartbeat presence/status/instance ID
- freshness state and heartbeat age
- last-success time and age
- active task
- recovery state
- last error
- decoded counters

## Freshness states

Default thresholds are intentionally conservative:

- `FRESH` — heartbeat age <= 120 seconds
- `LATE` — heartbeat age > 120 and <= 600 seconds
- `STALE` — heartbeat age > 600 seconds
- `MISSING` — service is recorded as `RUNNING` but no heartbeat exists
- `INVALID` — a running service has an unreadable heartbeat timestamp
- `NOT_EXPECTED` — the service is not recorded as `RUNNING`; heartbeat absence is not treated as a fault

This distinction prevents stopped or not-yet-started services from producing false stale-service alerts.

## Overall status

The snapshot status is:

- `ATTENTION` when a running service has `MISSING`, `STALE`, or `INVALID` heartbeat evidence
- `DEGRADED` when one or more running services are only `LATE`
- `HEALTHY` when all recorded running services have fresh heartbeats
- `IDLE` when no service is recorded as running

These statuses are diagnostic only. They do not automatically create lifecycle actions.

## Mission Control

Mission Control remains contract version 4 and advances the platform envelope to revision 2.

New headline fields include:

- `telemetry_status`
- `telemetry_running_services`
- `telemetry_fresh_running`
- `telemetry_late_running`
- `telemetry_attention_running`

Operator attention adds:

- `telemetry_attention_services`
- `telemetry_late_services`

The full telemetry snapshot is available at:

```text
platform.telemetry
```

All previously landed VM Brain surfaces, including canonical opportunities, Relationship Intelligence, Group/Search Intelligence, trust, and canonical review governance, remain additive and intact.

## Safety invariants

Passive telemetry is inspection-only:

- `read_only = true`
- `automatic_execution = false`
- `external_action_authority = false`

The milestone does not:

- start, stop, or restart bots
- execute recommendations
- accept recommendations automatically
- send Telegram messages
- modify VM Brain rules or thresholds
- create external action authority

## Validation

CI now validates the telemetry contract independently with `tools/ci/validate_vm_platform_telemetry.py` in addition to the Foundation and service-adapter contract validators.

Platform unit tests cover fresh, stale, missing, and non-running heartbeat semantics plus Mission Control integration.
