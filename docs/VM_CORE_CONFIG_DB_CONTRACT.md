# VM Core Configuration and Database Contract

VM Core 2.8 completes the main Core 1 shared-infrastructure primitives.

## Configuration registry

`configuration_registry` derives required and optional configuration **key names** from bot manifests.

It never stores environment values.

Generated runtime output:

```powershell
python vm.py registry config --write
```

writes `state/config_registry.json`.

## SQLite helpers

Shared SQLite helpers provide:

- explicit read-only connections
- quick/full integrity checks
- safe table-existence and column inspection
- an explicit write-transaction context using `BEGIN IMMEDIATE` by default

Bots are not forced to migrate their database internals immediately. The helper exists so future and migrated code can use one tested pattern rather than duplicating connection logic.

## Core 1 status

The shared platform now has reusable contracts for:

- service registry
- configuration
- paths
- structured logging
- Telegram identity/diagnostic helpers
- SQLite access
- per-bot service context
- manifests/foundation validation

The next development milestone is progressive bot adoption and then Core 2 Reliability.
