# VM Platform v4.1 — Service Adapters

VM Platform v4.1 adds the first bot-specific VM Core adapter layer on top of Foundation v4.0. The goal is to let Mission Control understand each active service more precisely without importing bot internals or granting new execution authority.

## Adapter contract

`shared.vm_core.service_adapters` defines a versioned, read-oriented adapter contract. Each adapter declares:

- service name and stable adapter ID
- confidence level
- preferred Python entrypoint
- preferred launcher
- known read surfaces
- high-level capabilities
- safe operations

The initial safe-operation set is deliberately limited to `status`, `health`, and `inspect`.

## Active adapters

The initial adapter registry covers all five permanent active bot folders:

- `Universal_Search` → `universal-search-v1`
- `VM_Guard` → `vm-guard-v1`
- `Admin_Command_Centre` → `admin-command-centre-v1`
- `VM_Relationship_Manager` → `relationship-manager-v1`
- `Smart_Auto_Poster_V2` → `smart-auto-poster-v1`

Adapter readiness is based only on repository evidence. Missing runtime databases are recorded as evidence debt because fresh CI checkouts may legitimately not contain generated runtime data. Missing expected entrypoints or launchers makes an adapter `EVIDENCE_REQUIRED`.

Unknown/future services remain `GENERIC_ONLY` and continue to use the generic manifest/service layer.

## Registry integration

The service registry schema advances to version 2 and now includes:

- `adapter_id`
- `adapter_status`
- `adapter_confidence`
- `adapter_safe_operations`

It also reports supported, ready, and evidence-required adapter counts.

## Health integration

The standard health record embeds the adapter evidence report under `detail.adapter`.

An expected high-confidence adapter whose runnable evidence is missing is treated as `DEGRADED`. Missing runtime read surfaces alone do not degrade health.

## Mission Control integration

Mission Control remains contract major version 4 and advances the platform envelope to revision 1:

```text
contract_version: 4
platform:
  contract_version: 4
  revision: 1
  registry: ...
  adapters: ...
  health: ...
  incident_intelligence: ...
```

Headline counts expose adapter coverage and readiness. Evidence-required adapters appear in the attention section.

## Safety boundary

Adapters do not start, stop, restart, message, post, accept recommendations, change rules, or perform external actions.

The following remain false:

- `automatic_acceptance`
- `automatic_execution`
- `external_action_authority`

Any future adapter operation beyond read/inspection must be introduced separately with explicit governance and tests.

## Next logical platform work

After v4.1, the next low-risk platform milestones are:

1. read-only bot-specific operational metrics through the adapter interface;
2. destination/account registry adapters where schemas are confirmed;
3. stale-health/heartbeat freshness semantics in Mission Control;
4. deeper recovery recommendations that remain advisory until separately authorised.
