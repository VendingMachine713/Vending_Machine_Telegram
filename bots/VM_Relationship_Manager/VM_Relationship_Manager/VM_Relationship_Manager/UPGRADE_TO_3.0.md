# VM Relationship Manager — Upgrade to v3.0.0

## Permanent folder

Extract this direct-update ZIP directly into:

`C:\Users\cherr\OneDrive\Desktop\Vending_Machine_Telegram\bots\VM_Relationship_Manager`

Choose **Replace** when Windows asks.

## Preserved automatically

The ZIP does not contain or replace:

- `.env`
- BotFather token/API credentials
- Telethon session/runtime files
- `vm_relationships.db`
- existing contacts, notes, tags, follow-ups, opportunities or history

## First startup protection

If the live database schema is older than 3.0.0, startup creates a verified consistent safety copy:

`shared\backups\VM_Relationship_Manager\pre_v3_YYYYMMDD_HHMMSS_ffffff.db`

A matching JSON manifest records its source schema, SHA-256, size and SQLite integrity result.

Only after that safety copy succeeds does the normal v3 database initialisation/migration proceed.

## Start

Run:

`.\START_VM_RELATIONSHIPS.bat`

Expected header:

`VM RELATIONSHIP MANAGER  v3.0.0`

The launcher will run the expanded local smoke test before starting Telegram services.

## First checks

In Telegram:

- `/rm`
- `/today`
- `/diagnostics`
- `/person @Phoenix_Plugs_Backup`
- `/groups`
- `/forecast`
- `/risks`
- `/report weekly`

## No credential changes required

v3 introduces no new mandatory `.env` values.
