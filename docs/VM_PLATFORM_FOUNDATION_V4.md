# VM Platform Foundation v4.0

VM Platform Foundation v4.0 hardens the shared platform boundary beneath VM Mission Control and VM Brain. It is intentionally additive: existing bot entrypoints, VM Brain intelligence behaviour, canonical review workflows, and operator safety controls remain unchanged.

## Scope

Foundation v4.0 standardises four passive platform surfaces:

1. **Service registry** — `shared.vm_core.platform_registry` discovers bot manifests and exposes stable service metadata without reading secret values.
2. **Health contract** — `shared.vm_core.health_contract` normalises service health into a versioned record with explicit `healthy` and `ready` semantics.
3. **Incident/intelligence aggregation** — `shared.vm_core.platform_aggregation` combines open incidents, active intelligence signals, actionable recommendations, and shared subjects for operator attention.
4. **Mission Control backend** — `shared.vm_core.mission_control` exposes the above surfaces under a versioned `platform` envelope while retaining the existing VM Brain response fields.

## Health contract

Each service health record contains:

- `contract_version`
- `service`
- `status`
- `healthy`
- `ready`
- `checked_at_utc`
- `detail`

Supported statuses are `ALIVE`, `READY`, `DEGRADED`, `CONFIG_REQUIRED`, `PLANNED`, and `UNKNOWN`.

`ALIVE` and `READY` are both healthy and ready. `PLANNED` is healthy as a declared placeholder but is not runtime-ready. `DEGRADED`, `CONFIG_REQUIRED`, and `UNKNOWN` are neither healthy nor ready.

The health scanner persists the same status/detail payload in `service_health`; `PlatformDB.health_records()` decodes those rows for passive Mission Control reads.

## Mission Control v4 envelope

`mission_control()` now includes:

```text
contract_version: 4
platform:
  contract_version: 4
  registry: ...
  health: ...
  incident_intelligence: ...
```

Existing top-level sections such as `headline`, `attention`, `opportunities`, `decisions`, `rule_health`, `canonical`, and `services` remain available for existing callers.

The platform envelope is read-oriented. It does not start or stop services and does not execute recommendations.

## Incident/intelligence aggregation

The aggregation surface reports:

- open incident count and severity/type counts
- active signal count and signal-type counts
- actionable (`PROPOSED`/`BLOCKED`) recommendation count
- recommendation status counts
- subjects appearing in both incident and intelligence data
- bounded source rows for operator inspection

Correlation is intentionally conservative: subjects correlate only when both `subject_type` and `subject_id` match exactly.

## Safety and authority

Foundation v4.0 does **not** grant VM Brain action authority. Mission Control and the aggregation contract continue to report:

- `automatic_acceptance = false`
- `automatic_execution = false`
- `external_action_authority = false`

Any future execution layer must be introduced as a separately reviewed capability with explicit policy and approval controls.

## Validation

The platform quality gate consists of:

- Python compilation for shared platform code, tests, CI tools, and `vm.py`
- unit tests under `tests/test_*.py`
- bot integration test jobs when shared platform code changes
- repository metadata validation
- `tools/ci/validate_vm_platform_contracts.py` for a dependency-light Foundation v4 contract smoke test

A v4 change is mergeable only after the required GitHub Actions checks are green.
