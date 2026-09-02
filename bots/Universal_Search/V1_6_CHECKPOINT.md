# Universal Search v1.6.0 — Match Engine v2 checkpoint

This checkpoint is stacked on v1.5 and must not bypass the preceding release chain.

## Added

- durable marketplace insert/update/delete event queue;
- event-driven matching in both supply→demand and demand→supply directions;
- SQL candidate pre-filtering for category, seller, and explicit WTB budget;
- direct revalidation of existing matches outside bounded candidate windows;
- WTB expiry/reminder state and durable reminder delivery queue;
- historical WTB no-reminder-flood handling, including WTBs imported after the v2 baseline;
- stale and superseded-admin reminder cancellation;
- admin `/matches`, `/match`, `/matchfeedback`, `/demandstats`, `/matchalerts` commands;
- explicit good/bad/accepted/ignore relevance feedback;
- advisory-only threshold calibration;
- demand coverage statistics;
- event-driven daemon with 15-second default consumption, 10-minute WTB lifecycle reconciliation, and 60-minute full-match reconciliation fallback;
- expanded Windows status/operator surfaces;
- v1.6 manifest, migration, temporary-schema quality gate, and regression coverage.

## Preserved

- existing Bot API polling process;
- historical backfill isolation;
- raw search/index data;
- saved watches and alerts;
- marketplace listings and price history;
- v1.5 match/feedback/alert data;
- singleton daemon lease and recovery behaviour.

## Safety

The match sidecar remains outbound-only and never calls Telegram `getUpdates`.

Threshold calibration never changes the configured production alert threshold automatically.

Existing historical WTBs are matchable but are not turned into an expiry-reminder flood.

## Validation gate

`VALIDATE.ps1` is no-send. It compiles Python, runs all `test_*.py` tests, validates the v1.6 manifest and required files, builds a temporary SQLite database to verify v2 tables/triggers, parses PowerShell launchers, and performs a read-only integrity check on an existing local database.

A GitHub Actions run that receives no runner (`runner_id=0`) and executes zero steps is an infrastructure allocation failure and does not count as application validation.
