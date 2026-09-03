# VM Relationship Manager — Upgrade to v5.0.0

v5.0 is the autonomy major release built on the verified v4.0.1 production baseline.

## What changes

- Adds confidence-aware automatic relationship-type classification.
- Adds a deduplicated recommended-action / exception queue.
- Adds SAFE / ASSIST / OBSERVE autonomy modes.
- Adds automatic suppression of empty daily digests.
- Adds safe self-healing maintenance and maintenance audit history.
- Extends integration exports with classification/action state.
- Extends search, profiles, reports, diagnostics and executive briefs.

## Safety model

The default mode is **SAFE**. SAFE mode may perform reversible metadata maintenance and apply only high-confidence classifications from a deliberately limited safe type set. It never sends messages to contacts, changes Telegram permissions, makes purchases, closes deals, or takes external commercial actions.

Manual relationship-type changes create a classifier lock. Existing non-unknown v4 types are never automatically overwritten.

## Migration / recovery

At first v5 startup:

1. A verified `pre_v5_*.db` SQLite safety snapshot is created if the live schema is older than 5.0.0.
2. Schema migrations run in place.
3. A verified `post_v5_upgrade` backup is created and recorded in `backup_audit`.

The package does not contain or replace `.env`, Telegram session files, credentials, or the live relationship database.

## First live checks

After startup:

- `/version`
- `/doctor`
- `/autonomy`
- `/classify`
- `/exceptions`
- `/brief`

`/doctor` should report schema 5.0.0 and SQLite/backup health as OK/VERIFIED.
