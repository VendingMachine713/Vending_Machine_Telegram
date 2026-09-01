# Technical Debt Register

## TD-001 â€” Relationship Manager nested duplicate merge
Priority: High
The nested folder contains differing files. v1.3 captures a redacted unified text diff in support bundles.
Do not delete until those differences are deliberately reconciled.

## TD-002 â€” Smart Auto Poster deep VM Core adoption
Priority: Medium
The live bot remains independently runnable. Shared infrastructure should be adopted incrementally.

## TD-003 â€” Bot-specific search adapters
Priority: Medium
Universal Search v1.0 includes generic read-only SQLite message discovery. Explicit adapters can improve
precision as each bot schema is confirmed.

## TD-004 â€” Ruff cleanup
Priority: Low
Ruff/uv tooling remains available through the platform, but style cleanup should not block operational releases.
