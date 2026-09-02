# VM Platform v1.0 Feature Matrix

## Operational in v1.0

- Shared VM Core library
- Platform SQLite DB and schema migration tracking
- Bot manifests, inventory, safe structure inspection
- VM Doctor
- Service dashboard and status
- Preview-first start/stop/restart, including `all`
- Preview-first self-healing supervisor policy
- Shared health checks
- Structured JSONL logs
- SQLite-safe local backups
- Dry-run rollback with pre-rollback safety backup
- Account registry from session filenames only
- Read-only destination registry discovery from compatible bot databases
- Persistent job queue and event store
- Safe simulation scenarios
- Environment/dependency inventory and optional dependency setup
- Ruff integration when installed
- Release pre-flight gate
- Per-bot release baseline and delta package builder
- Safe support bundle generation
- Git-ready ignore template and GitHub Actions CI scaffold
- Windows control panel and CMD-safe installer
- Persistent self-healing supervisor loop
- Optional Docker Compose and Railway deployment scaffolding

## Integration-ready, but requires each live bot's confirmed internals

- Direct shared Telegram client/session helpers inside every bot
- Admin Command Centre Telegram UI over the platform DB
- Exact destination adapters for every bot schema
- Direct event ingestion from each live bot
- Delegated job execution into bot-specific services
- Bot-specific automatic recovery policies

These are intentionally adapter-based rather than forced rewrites so existing bots remain independently runnable.
