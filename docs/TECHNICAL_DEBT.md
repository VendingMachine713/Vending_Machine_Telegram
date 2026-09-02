# Technical Debt Register

## TD-001 — Bot-specific VM Core adapters
Priority: High
The five bots are discovered and managed generically. Deep bot-specific adapters should be added as each bot reaches its next milestone.

## TD-002 — Relationship Manager nested duplicate folder
Priority: High
Detected in VM Doctor. Do not automatically delete; inspect/classify contents before cleanup.

## TD-003 — Unknown entrypoints
Priority: High
Admin Command Centre, Universal Search and VM Guard require structure inspection if generic detection cannot resolve launch targets.

## TD-004 — Auto Poster stale runtime-lock Windows test
Priority: Medium
A recent test run was interrupted during Windows temporary-directory handling. Preserve the live service; harden the regression test in the next Auto Poster milestone.

## TD-005 — Destination registry adapters
Priority: Medium
v1.0 can discover destination-like tables read-only; add explicit adapters for each bot database as schemas are confirmed.
