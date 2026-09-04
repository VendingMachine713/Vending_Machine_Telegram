# VM Relationship Manager

A passive Telegram relationship-management and private Business Memory service for the Vending Machine ecosystem.

## Current capabilities

- Automatic contact profiles keyed by permanent Telegram ID
- Username/display-name change history
- Shared-group tracking
- Activity and active-day tracking
- Relationship types, tags and verification states
- Transparent relationship, trust and health scores
- Momentum/lifecycle intelligence and learned contact cycles
- Cooling/dormant detection
- Follow-ups, private notes and event timeline
- Ranked `/today` admin-by-exception inbox
- Daily/weekly relationship briefs
- SQLite WAL database with transactional backups
- Admin audit and health logs
- Business Memory for client/supplier/product transaction history
- Product-centric client/supplier views
- Passive reload and dormant-client business signals
- Privacy-reduced canonical VM Brain signal bridge
- Low-touch business capture directly from contact-profile buttons

## Privacy design

The monitor is metadata-first. It does **not** save message bodies by default.

It records identity/activity metadata and aggregate relationship information. Private notes entered by authorised admins are stored locally. Business Memory stores only business facts explicitly recorded/imported by the operator; it does not infer sales or supplier transactions from ordinary Telegram messages.

The canonical Business Memory bridge does not copy private notes, message bodies, usernames, display names, raw Telegram contact IDs or product names into shared Brain evidence.

## Telegram limitation

The monitoring account can only observe chats/messages that the authorised Telegram account can legitimately access. A normal Telegram bot cannot silently read arbitrary groups it is not in or bypass Telegram permissions.

## Setup

### 1. Install Python

Python 3.11+ recommended.

### 2. Create a Telegram API application

Create an `api_id` and `api_hash` for your own Telegram account through Telegram's official API development page.

### 3. Create the private admin bot

Create a Telegram bot through BotFather and store its token only in `.env`.

### 4. Configure

Copy `.env.example` to `.env` and fill in:

```text
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=
BOT_TOKEN=
ADMIN_IDS=
```

`ADMIN_IDS` is a comma-separated list of Telegram numeric IDs allowed to control Relationship Manager.

### 5. Install dependencies

```powershell
py -m pip install -r requirements.txt
```

### 6. Run

Preferred Windows launcher:

```powershell
.\START_VM_RELATIONSHIPS.bat
```

Direct Python startup also works when the environment is already configured:

```powershell
py main.py
```

The first Telethon run may ask for the Telegram login code and, if enabled, your 2FA password. The session is then stored locally and must not be committed.

## Primary admin commands

```text
/rm
/person @username
/person TELEGRAM_ID
/today
/insights
/growing
/slipping
/attention
/followups
/dormant
/cooling
/top
/health
/rescan
```

You can also send a name or username directly to the private admin bot to search.

## Low-touch Business Memory workflow

The normal workflow does **not** require editing CSV files or manually finding Telegram IDs.

1. Open a known contact with `/person @username`, `/person TELEGRAM_ID`, or normal contact search.
2. Tap **💼 + Client deal** or **📦 + Supplier deal** on the profile.
3. Tap one of the suggested products to record one unit immediately, or send a new product name as the next message.
4. If the contact has previous business history, **🔁 Repeat last business deal** can repeat the last role/product/quantity/unit in one tap.

Quick capture deliberately does not infer monetary value. Use the full `/deal` command only when quantity, value or a note matters.

A pending quick-capture prompt expires automatically after five minutes. Tap **Cancel** or send `cancel` while the prompt is active to return to normal contact search.

## Full Business Memory controls

```text
/business
/deal client @user | Product | 2 | 120.00 | optional note
/deal supplier @user | Product | 10 | 500.00 | optional note
/history @user
/clients [product]
/suppliers [product]
/product Product Name
/reload Product Name
/touchbase [days]
/available Product Name | optional note
/unavailable Product Name | optional note
```

Availability and reload/touch-base views are review-first. No client or supplier is messaged automatically.

## Historical bulk import

`import_business_history.py` remains available for genuine bulk migration/recovery when a real historical transaction source already exists.

Dry-run first:

```powershell
py import_business_history.py .\business_history_template.csv
```

Apply only after validation reports zero problems:

```powershell
py import_business_history.py .\business_history_template.csv --apply
```

The CSV importer is not the normal day-to-day recording workflow.

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

## Scoring boundary

Relationship score is transparent and deterministic. It uses relationship activity/recency/consistency signals. Trust remains separate from relationship strength.

Business transaction value is informational history only. It does not automatically increase trust or relationship quality.

## Important files

```text
main.py
config.py
database.py
relationship_engine.py
monitor.py
admin_bot.py
business_memory.py
business_admin.py
business_integration.py
business_quick_capture.py
business_product.py
business_signals.py
business_import.py
import_business_history.py
business_history_template.csv
jobs.py
requirements.txt
.env.example
tests/
```

## Testing

Run Relationship Manager tests from this directory:

```powershell
py -m unittest discover -s tests -p "test_*.py" -v
```

GitHub Actions also compiles and tests Relationship Manager as part of VM Platform CI.

## Backup and reliability

- SQLite runs in WAL mode.
- Backups use SQLite's transactional backup API so committed WAL-backed Business Memory rows are included.
- Background relationship intelligence refresh runs periodically.
- Daily/weekly operator briefs are passive and admin-only.
- No Business Memory workflow has automatic client/supplier outreach authority.

## Digest schedule

Default timezone: `Australia/Adelaide`.

```text
DAILY_DIGEST_HOUR=9
WEEKLY_DIGEST_WEEKDAY=1
WEEKLY_DIGEST_HOUR=9
```

python-telegram-bot weekday numbering is Sunday=0 through Saturday=6.
