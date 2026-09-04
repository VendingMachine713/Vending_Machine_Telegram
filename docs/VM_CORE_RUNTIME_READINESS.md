# VM Core 2.9 — Runtime Registry and Core 1 Readiness

VM Core 2.9 closes the main Core 1 Foundation visibility gap: one canonical runtime snapshot for every registered bot and one readiness report for the Foundation milestone.

## Runtime registry

```powershell
python vm.py registry runtime
python vm.py registry runtime --write
```

The generated registry contains only operational metadata:

- service name/version
- managed lifecycle flag
- runtime state
- process-alive state
- PID
- entrypoint/launcher

It does not include process command lines, environment values, Telegram tokens or credentials.

Generated state is written to `state/runtime_registry.json`.

## Core 1 readiness

```powershell
python vm.py core-readiness
```

The readiness gate verifies:

- Foundation contract
- service registry
- configuration registry
- runtime registry

It also reports incremental adoption of `ServiceContext`, shared event publishing and shared logging by each bot. Adoption is informational so existing working bots can migrate safely over time rather than through a risky rewrite.

## Milestone interpretation

A PASS means the shared infrastructure needed for Core 1 exists and can describe the entire platform consistently.

The next work is incremental bot adoption followed by Core 2 Reliability: heartbeat standards, health classification, watchdog supervision and safe recovery.
