# VM Brain Audit and Shadow Mode

Status: Trust Layer milestone 1.3

## Purpose

This milestone makes VM Brain easier to inspect and safer to evolve. It adds two
passive capabilities:

1. a read-only intelligence audit/query surface; and
2. a shadow-mode comparison gate for candidate Brain behavior.

Neither capability grants authority to execute Telegram actions.

## Audit surface

`shared.vm_core.intelligence_audit` reads the existing VM event ledger using a
SQLite read-only connection. It does not initialize, migrate, or create platform
state when the database is absent.

Queries may be bounded by:

- intelligence event prefix
- source service
- subject type
- subject ID
- correlation ID
- result limit

`audit_summary()` provides compact counts by intelligence kind, source and subject
type plus mean recorded confidence where available.

## Shadow mode

`shared.vm_core.intelligence_shadow` compares baseline and candidate intelligence
outputs using the stable replay fingerprints introduced in Trust Layer 1.2.

A `ShadowPolicy` defines acceptable behavioral change budgets:

- maximum newly produced outputs
- maximum removed outputs
- maximum total change ratio
- whether a non-empty baseline is mandatory

If a candidate exceeds those budgets, the result is `REVIEW_REQUIRED`.

A `PASS` means only that the candidate remained inside the configured shadow
budget. It does not approve recommendations, increase autonomy, or execute work.

## Safety invariants

- audit operations are read-only
- missing databases are not created
- shadow evaluation performs no writes
- no Telegram actions are available through these modules
- `automatic_execution` is always false
- large behavioral deltas fail into review rather than being silently accepted

## Next milestone

After this branch passes CI:

1. migrate a selected Relationship Manager signal to the canonical Trust Layer
   record contract in parallel with the legacy signal;
2. validate both outputs in shadow mode;
3. preserve backward compatibility while cross-bot consumers migrate;
4. add first canonical cross-bot correlation between Relationship Manager and
   Universal Search evidence.
