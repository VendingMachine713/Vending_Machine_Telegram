# VM Core Foundation Contract

VM Core Foundation defines the minimum platform contract shared by every permanent bot.

## Contract v1

Every canonical bot must have a readable `BOT_MANIFEST.json` with:

- schema version 3 or newer
- a manifest `name` matching the permanent bot folder
- a version and classification
- a valid entrypoint or launcher
- `vm_core.compatible: true`
- lifecycle booleans for `managed_by_vm`, `auto_start`, and `auto_restart`
- optional capabilities as a list of non-empty strings
- optional runtime requirements as an object

The platform registry in `VM_PROJECT.json` remains the source of truth for permanent bot folders.

## Validation

Run:

```powershell
python vm.py foundation
```

The command is read-only. It reports PASS, WARN, or FAIL and does not expose environment values or credentials.

Core 1 is considered complete when every declared bot passes this contract and uses VM Core shared configuration, logging, paths, database helpers, and service interfaces.
