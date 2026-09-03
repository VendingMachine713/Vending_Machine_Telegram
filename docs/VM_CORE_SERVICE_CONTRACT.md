# VM Core Foundation — Service Contract v2.6

VM Core 2.6 continues Core 1 Foundation by turning the existing bot manifests into one stable platform service registry.

## Shared service registry

Every permanent bot can now be represented by the same descriptor:

- identity and version
- permanent folder and entrypoint
- launcher candidates
- capabilities
- required and optional configuration key names
- lifecycle ownership
- auto-start / auto-restart policy flags
- database and test inventory
- manifest location

The registry deliberately records configuration **key names only**. It does not read or persist secret values.

Read it with:

```powershell
python vm.py registry services
```

To write the generated runtime registry:

```powershell
python vm.py registry services --write
```

Generated output is written under `state/` and is operational state, not canonical source.

## Shared paths

VM Core now owns standard helpers for bot roots, state paths and sanitized structured-log paths. Future bot integrations should use these helpers instead of inventing new root/path discovery rules.

## Shared Telegram helpers

The Core provides fail-closed numeric Telegram ID parsing, numeric-ID set normalization, token-shaped diagnostic redaction and non-authoritative peer display labels.

Usernames and display names are never treated as authorization identities.

## Shared structured logging

Structured JSONL logging now:

- uses centralized safe log paths
- recursively redacts secret-like keys
- redacts Telegram Bot API token-shaped values embedded in strings
- preserves JSON-compatible operator diagnostics

## Core 1 direction

The remaining Foundation work is to migrate each bot incrementally onto these shared contracts without rewriting or destabilizing working bot internals.
