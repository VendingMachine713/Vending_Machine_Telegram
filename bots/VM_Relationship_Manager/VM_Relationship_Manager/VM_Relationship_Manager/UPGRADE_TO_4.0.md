# VM Relationship Manager — Upgrade to v4.0.0

## Permanent folder

Extract the v4 direct-drop ZIP directly into:

`C:\Users\cherr\OneDrive\Desktop\Vending_Machine_Telegram\bots\VM_Relationship_Manager`

Choose **Replace** when Windows asks.

## Preserved

The update does not contain or replace:

- `.env`
- BotFather token
- Telegram API credentials
- `runtime/` Telethon session files
- the live `vm_relationships.db`
- existing relationship history, notes, tags, memories, opportunities or contacts

Your currently authorised `runtime/vm_relationship_backup` session remains untouched because runtime files are excluded from the package.

## First v4 startup

When the existing schema is older than 4.0.0, startup creates a verified `pre_v4_*.db` SQLite safety backup before opening the database with the new schema.

The upgrade is non-destructive and preserves existing v3 data.

## Start

`.\START_VM_RELATIONSHIPS.bat`

The launcher should display:

`VM RELATIONSHIP MANAGER  v4.0.0`

Then the normal smoke test must pass before the live process starts.

## First Telegram checks

- `/rm`
- `/brief`
- `/today`
- `/doctor`
- `/person @Phoenix_Plugs_Backup`
- `/segments`

## Local fallback doctor

If startup fails before Telegram control becomes available:

`py .\VM_RM_LOCAL_DOCTOR.py`
