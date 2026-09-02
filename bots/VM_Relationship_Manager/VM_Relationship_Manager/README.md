# VM Relationship Manager — Master Project Build

# VM Relationship Manager V1

A passive Telegram relationship-management service for the Vending Machine ecosystem.

## V1 includes

- Automatic contact profiles keyed by permanent Telegram ID
- Username/display-name change history
- Shared-group tracking
- Activity and active-day tracking
- Relationship types and tags
- Verification states
- Relationship score
- Trust score
- Learned contact-cycle estimate
- Cooling/dormant detection
- Manual follow-ups
- Private admin notes
- Meaningful event timeline
- Attention queue
- Admin Telegram bot dashboard
- Search by ID, username or name
- Daily score recalculation
- SQLite WAL database
- Rolling database backups
- Admin audit log
- Health log

## Privacy design

The monitor is metadata-first. It does **not** save message bodies by default.

It records who interacted, when, where, and aggregate relationship information.
Private notes entered by authorised admins are stored.

## Important Telegram limitation

The monitoring account can only observe chats/messages that the authorised Telegram account can legitimately access. A normal Telegram bot cannot silently read arbitrary groups it is not in or bypass Telegram permissions.

## Setup

### 1. Install Python

Python 3.11+ recommended.

### 2. Create a Telegram API application

Get `api_id` and `api_hash` from Telegram's official API development page for your own account.

### 3. Create the admin bot

Create a Telegram bot through BotFather and copy its token.

### 4. Configure

Copy:

```text
.env.example
```

to:

```text
.env
```

Fill in:

```text
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=
BOT_TOKEN=
ADMIN_IDS=
```

`ADMIN_IDS` is a comma-separated list of Telegram numeric IDs allowed to control the Relationship Manager.

### 5. Install

Windows PowerShell:

```powershell
py -m pip install -r requirements.txt
```

### 6. Run

```powershell
py main.py
```

The first Telethon run may ask for the Telegram login code and, if enabled, your 2FA password. The session is then stored locally.

## Admin commands

```text
/rm
/relationships
/person @username
/person TELEGRAM_ID
/note TELEGRAM_ID private note here
/tag TELEGRAM_ID tag
/type TELEGRAM_ID regular
/verify TELEGRAM_ID verified optional reason
/followup TELEGRAM_ID 7d reason
/attention
/dormant
/vip
/regulars
/health
```

You can also simply send a name or username to the admin bot to search.

## Relationship types

```text
unknown
prospect
customer
regular
vip
supplier
vendor
partner
admin
group_owner
```

## Verification states

```text
unknown
pending
verified
trusted
restricted
```

## V1 scoring

Relationship score is intentionally transparent and deterministic. It uses:

- recency
- interaction frequency
- relationship duration
- active-day consistency
- important events
- manual importance
- shared-group presence

Trust is deliberately separate from relationship strength.

Automated risk signals should be reviewed before serious trust penalties are applied.

## Files

```text
main.py
config.py
database.py
relationship_engine.py
monitor.py
admin_bot.py
jobs.py
requirements.txt
.env.example
```

## Planned integration points

The database/module boundaries are intentionally separated so later versions can integrate:

- VM Guard
- VM Universal Search
- VM Auto Poster engagement
- VM Reputation
- VM Admin Command Centre

## Optional local smoke test

Before connecting Telegram, you can validate the database and relationship engine:

```powershell
py smoke_test.py
```

Expected output includes:

```text
SMOKE TEST PASSED
```

## Digest schedule

Daily and weekly relationship briefs are sent to authorised admin IDs after those admins have started the bot at least once.

Default timezone: `Australia/Adelaide`

Configure in `.env`:

```text
DAILY_DIGEST_HOUR=9
WEEKLY_DIGEST_WEEKDAY=1
WEEKLY_DIGEST_HOUR=9
```

python-telegram-bot weekday numbering is Sunday=0 through Saturday=6.


## Master project placement

This build belongs permanently at:

```text
Vending_Machine_Telegram/
└── bots/
    └── VM_Relationship_Manager/
```

Runtime data is automatically sorted into the existing master project:

```text
shared/
├── exports/
│   └── VM_Relationship_Manager/
├── backups/
│   └── VM_Relationship_Manager/
└── logs/
    └── VM_Relationship_Manager/
```

The Telethon session stays inside:

```text
bots/VM_Relationship_Manager/runtime/
```

## Recommended Windows launch

From the master project:

```powershell
cd .\bots\VM_Relationship_Manager
.\START_VM_RELATIONSHIPS.ps1
```

The launcher:
1. checks for `.env`
2. offers to copy `.env.example` if needed
3. installs requirements when requested
4. runs the smoke test
5. starts the bot


## Windows launcher update — v1.0.2

Preferred launch method on Windows:

```text
START_VM_RELATIONSHIPS.bat
```

Double-clicking the BAT file launches the existing PowerShell startup script with a
process-only execution-policy bypass. It does not permanently change the computer's
PowerShell execution policy.

The launcher now checks:
1. Python dependencies, including `tzdata`
2. `Australia/Adelaide` timezone availability
3. `.env` configuration via `preflight.py`
4. relationship-engine smoke test
5. live bot startup
