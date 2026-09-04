# Technical Debt Register

## TD-001 — Bot-specific VM Core adapters
Priority: High
Status: Foundation resolved in v4.1
The five active bots now have conservative VM Core adapter profiles with validated repository evidence, read surfaces, capabilities, and safe operations. Deeper bot-internal adapters remain incremental work and must not bypass existing bot boundaries.

## TD-002 — Relationship Manager nested duplicate folder
Priority: High
Detected in VM Doctor. Do not automatically delete; inspect/classify contents before cleanup.

## TD-003 — Unknown entrypoints
Priority: High
Status: Resolved for the five active bots
Admin Command Centre, Universal Search, VM Guard, VM Relationship Manager, and Smart Auto Poster now have high-confidence manifest entrypoints and adapter evidence. Preserve generic detection for future/unknown services.

## TD-004 — Auto Poster stale runtime-lock Windows test
Priority: Medium
A recent test run was interrupted during Windows temporary-directory handling. Preserve the live service; harden the regression test in the next Auto Poster milestone.

## TD-005 — Destination registry adapters
Priority: Medium
v1.0 can discover destination-like tables read-only; add explicit adapters for each bot database as schemas are confirmed.
