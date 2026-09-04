# Smart Auto Poster v6 Delivery Reconciliation

This reconciliation preserves the useful v6 delivery-safety requirements while keeping the current platform ownership boundary intact.

## Smart Auto Poster owns

- scheduling and queueing
- outbound Telegram delivery
- per-account routing and pacing
- media staging/cache state
- delivery ledger and recovery
- circuit-breaker/safety behavior
- Smart Auto Poster database and diagnostics

## Admin Command Centre owns

- Telegram admin bot authentication
- Telegram control UI
- cross-service status/progress presentation
- explicit service control actions

Smart Auto Poster does not start or supervise an embedded Telegram admin bot.

## Delivery behavior

- Cached Telegram media references are reused while valid.
- If Telegram reports an expired file reference, only the affected album cache entry is invalidated.
- Original local media is restaged once and the destination send is retried once; there is no unbounded media retry loop.
- Album sends use a bounded adaptive timeout, capped at 180 seconds; a ten-photo album receives the full 180-second window.
- Each Telegram account permits at most one in-flight send.
- The service runs a bounded two-slot delivery batch so primary and secondary can make progress concurrently.
- A destination's preferred account remains preferred while healthy. If that account's health has collapsed and a healthier accessible authorised account exists, delivery may fail over.
- Retry/deferred queue items are unpinned when reclaimed so a previous failed account does not permanently own the retry.

## Fail-closed boundary

`UNCERTAIN` means delivery may already have reached Telegram but local confirmation is incomplete. UNCERTAIN rows are never automatically reclaimed or retried. Interrupted `sending` rows continue to become UNCERTAIN during startup recovery.

## Validation

Regression tests cover media invalidation/restaging, expired-reference recovery, timeout bounds, per-account send serialisation, account failover, retry unpinning, UNCERTAIN exclusion and absence of embedded Smart Auto Poster admin-runtime ownership.

Live Windows verification must not activate or create a production campaign merely to test this migration. Existing queue/campaign state should be observed and preserved.
