# Telegram Admin Control Centre â€” V3.0

The Admin Control Centre is optional. Smart Auto Poster can run without it.

Configure locally in `.env`:

```text
ADMIN_BOT_TOKEN=
ADMIN_USER_IDS=
ADMIN_READONLY_USER_IDS=
ADMIN_BOT_SESSION=runtime/admin_bot
ADMIN_NOTIFICATIONS_MIN_SEVERITY=IMPORTANT
```

- `ADMIN_USER_IDS`: comma-separated Telegram numeric user IDs with control permission.
- `ADMIN_READONLY_USER_IDS`: optional dashboard/report-only users. Read-only users cannot activate/pause campaigns, mutate destinations/jobs, apply recommendations, Post Now, or pause/resume the service.

Never paste a bot token, API hash, Telegram login code, 2FA password or `.session` contents into chat or diagnostics.

Use Control Panel option **52** to inspect admin-bot readiness and option **53** to run only the Admin Bot for a controlled test. The full V3 service supervises the Admin Bot task when enabled.

Telegram views include dashboard, campaigns, content, accounts, queue/errors, destination review/search, collections, recommendations and daily/weekly reports. Control admins also get campaign lifecycle actions, Post Now through the normal safety queue, job retry/cancel/defer, destination protection/never-auto-post, recommendation apply/dismiss, emergency pause/resume and the campaign wizard.
