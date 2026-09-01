# VM Platform v1.3.0

The consolidated productivity, automation and intelligence foundation for the permanent `Vending_Machine_Telegram` project.

## Working capabilities

- Bot discovery + manifests + machine-readable inventory
- Shared platform SQLite database with migrations
- Versioned structured event contract shared by all current bots
- Shared incidents + intelligence signal persistence
- Cross-bot VM Intelligence materialisation layer
- Admin Command Centre `/intelligence` and `/brain` read-only intelligence view
- Failure-isolated `BotEventPublisher` so telemetry cannot crash production bots
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

## VM Intelligence architecture

All currently runnable bots publish operational evidence into VM Core through `shared.vm_core.publisher.BotEventPublisher`.

The current integration publishes:

- service lifecycle and heartbeat evidence
- runtime incidents
- VM Guard elevated-risk signals
- Universal Search activity signals
- existing shared service health / registry evidence

VM Intelligence materialises explainable incidents and cross-bot signals from that evidence. It does not directly mutate bot-owned databases or perform operational actions. This keeps reasoning evidence-governed and allows future automation to add explicit authority gates.

See `docs/VM_INTELLIGENCE.md` for the event contract and extension rules.

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

From the Admin Command Centre, use:

```text
/intelligence
/brain
```

## Deep bot integration

VM Core does not replace bot-specific storage or proven operational logic. Each bot remains independently runnable. Shared adapters progressively centralise evidence, health, incidents and intelligence while preserving existing behaviour.

## Live-project validation

Run one command:

```powershell
py vm.py validate-all
```

or choose **19. FULL PLATFORM VALIDATION + SUPPORT BUNDLE** in `VM_CONTROL.bat`.

Reserved bot folders with no runnable code are shown as `PLANNED`, not as failures.
Nested duplicate folders are compared by SHA-256 and never deleted automatically.
