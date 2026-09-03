# VM Core Bot Integration Contract

VM Core 2.7 adds a lightweight `ServiceContext` so each bot can consume shared platform infrastructure through one stable entry point.

## Intended use

A bot can resolve its platform context:

```python
from shared.vm_core.service_context import service_context

vm = service_context("VM_Guard")
```

The context exposes:

- canonical service identity and version
- declared capabilities
- required configuration key names
- permanent bot-root paths
- standardized per-service runtime state paths
- structured, secret-redacting logging
- the shared event publisher

## Migration rule

Bots should migrate incrementally.

Do not replace working internals in one rewrite. Prefer:

1. shared path/context adoption
2. shared logging adoption
3. shared event publishing
4. shared config/runtime requirement validation
5. later lifecycle/health/recovery integration

This preserves independent failure domains while progressively removing duplicated infrastructure.
