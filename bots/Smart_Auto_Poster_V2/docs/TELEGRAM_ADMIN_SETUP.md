# Telegram Administration — Ownership Redirect

Smart Auto Poster no longer owns a Telegram administration bot.

## Canonical owner

Use:

```text
bots/Admin_Command_Centre/
```

for Telegram administration, authentication, control UI, service status and Smart Auto Poster progress surfaces.

Configure admin credentials only in the Admin Command Centre local `.env` using its documented `VM_ADMIN_*` settings. Do **not** add legacy `ADMIN_BOT_TOKEN`, `ADMIN_USER_IDS`, `ADMIN_READONLY_USER_IDS` or `ADMIN_BOT_SESSION` settings to Smart Auto Poster.

Smart Auto Poster owns posting, scheduling, queueing, delivery recovery, safety, media caching, delivery intelligence and its own database. It does not start or supervise `TelegramAdminController`.

See:

```text
bots/Admin_Command_Centre/README.md
docs/ADMIN_COMMAND_CENTRE.md
```

Never paste a bot token, API hash, Telegram login code, 2FA password or `.session` contents into chat or diagnostics.
