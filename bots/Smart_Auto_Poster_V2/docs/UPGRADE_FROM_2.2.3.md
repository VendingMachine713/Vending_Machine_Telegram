# Direct upgrade: V2.2.3+ to V3.0

Smart Auto Poster V3.0 is a consolidated upgrade. V2.3/V2.4 do not need to be installed first.

The release package contains source, tests, docs and update tooling only. It intentionally does **not** contain or replace `.env`, Telegram `.session` files, the live SQLite database, destination CSV, user content, media cache, logs or diagnostics.

## Safe upgrade flow

1. Stop Smart Auto Poster and confirm no `runtime\telegram_runtime.lock` remains from a live process.
2. Run the V3.0 one-time installer, or put the V3.0 ZIP into `Vending_Machine_Telegram\updates\inbox` and run `APPLY_UPDATE.ps1` once the master updater is installed.
3. Before changes, the updater verifies the manifest, exact payload membership and SHA-256 hashes, then backs up changed source files and takes a consistent SQLite online backup.
4. V3.0 migrates the database additively to schema v6.
5. Post-update verification compiles the code, runs the full test suite, runs local validation and checks SQLite integrity.
6. If verification fails, source files **and the database snapshot** are restored automatically.
7. After success, use the Control Panel: Health â†’ Validate â†’ Account Identities â†’ `LIVE_TEST` dry-run/one controlled send.
8. Only after the canary succeeds should unattended production be resumed.

## Preservation regression test

The release process reconstructs historical V2.2.3 from its original bootstrap/delta packages and seeds schema v3 with a live-shaped enabled campaign plus a sent queue record. Direct upgrade to schema v6 preserves the campaign, priority, tags, content reference, queue status, run key and Telegram message IDs, then passes the full V3 suite and SQLite integrity check.
