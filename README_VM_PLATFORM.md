# VM Platform v1.1.0

The first consolidated productivity and automation foundation for the permanent `Vending_Machine_Telegram` project.

## Working capabilities

- Bot discovery + manifests + machine-readable inventory
- Shared platform SQLite database with migrations
- VM Doctor and safe structure inspection
- Unified service status, dashboard and lifecycle preview/apply commands
- Shared health protocol
- Preview-first self-healing supervisor policy (`auto_start` / `auto_restart`)
- `start all`, `stop all`, and `restart all` lifecycle control
- Structured JSONL platform logs
- Safe local backups using SQLite's backup API
- Dry-run rollback with safety backup before an applied rollback
- Shared account registry from session filenames (session contents are never read)
- Read-only destination registry discovery from compatible SQLite schemas
- Persistent jobs and events
- Safe simulation scenarios
- Environment/dependency inventory and optional dependency setup
- Ruff lint/format integration when Ruff is installed
- Release pre-flight checking
- Per-bot release baseline + changed/new-file delta builder
- Safe support bundle generator
- Git-ready exclusions and GitHub Actions-ready CI
- Windows VM control panel
- Persistent supervisor loop for unattended operation
- Optional Docker Compose + Railway deployment scaffolding

## Important safety defaults

`start`, `stop`, `restart`, `rollback`, and dependency setup preview first.

Examples:

```powershell
py vm.py start autoposter
py vm.py start autoposter --apply

py vm.py rollback
py vm.py rollback --apply

py vm.py setup
py vm.py setup --apply
```

## Main control

Double-click:

`VM_CONTROL.bat`

or run:

```powershell
py vm.py dashboard
```

## Deep bot integration

v1.0 deliberately does not rewrite unknown bot internals. Bots remain independently runnable. As each bot reaches its next milestone, shared adapters can replace duplicated infrastructure incrementally.


## v1.1 live-project validation

Run one command:

```powershell
py vm.py validate-all
```

or choose **19. FULL PLATFORM VALIDATION + SUPPORT BUNDLE** in `VM_CONTROL.bat`.

Reserved bot folders with no runnable code are now shown as `PLANNED`, not as failures.
Nested duplicate folders are compared by SHA-256 and never deleted automatically.
