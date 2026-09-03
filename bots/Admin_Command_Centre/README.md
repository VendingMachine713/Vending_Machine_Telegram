# VM Admin Command Centre v0.3.0

The Admin Command Centre is the single Telegram administration surface for the Vending Machine Telegram ecosystem. Individual bots should not own duplicate admin Telegram bots.

## Setup

1. Copy `.env.example` to `.env`.
2. Add only `VM_ADMIN_BOT_TOKEN`.
3. Start the bot. If no admin is configured, the Windows console prints a one-time claim code.
4. Send `/claim <code>` to the bot in a private chat. Your numeric Telegram user ID is stored locally automatically.
5. Keep `VM_ADMIN_ALLOW_MUTATIONS=false` until read-only commands are verified.

## Smart Auto Poster controls

Read-only commands:

- `/poster` - show Smart Auto Poster controls.
- `/poster_status` - VM-managed runtime status and PID.
- `/poster_progress` - live Universal Progress Engine view using Smart Auto Poster's read-only queue/destination adapter.
- `/poster_health` - run Smart Auto Poster's existing `health` CLI through VM Core.
- `/poster_queue` - run Smart Auto Poster's existing `queue-capacity` CLI through VM Core.
- `/poster_campaigns` - run Smart Auto Poster's existing `campaigns` CLI through VM Core.

Mutating commands require `VM_ADMIN_ALLOW_MUTATIONS=true`:

- `/poster_start`
- `/poster_stop`
- `/poster_restart`

## Universal Progress Engine CLI

The same read-only progress snapshot can be rendered locally without starting Telegram administration:

```powershell
python -m shared.vm_core.progress_cli autoposter
python -m shared.vm_core.progress_cli autoposter --json
```

The progress surface never sends posts, changes queue rows, retries uncertain deliveries, or modifies campaign/schedule state.

## Architecture boundary

`Admin_Command_Centre` owns Telegram administration and authentication.

`Smart_Auto_Poster_V2` owns posting, scheduling, queueing, recovery, safety and its own data.

Cross-bot operations use `shared/vm_core` service interfaces. Admin Command Centre does not import Smart Auto Poster internal modules. The Universal Progress Engine reads explicit Smart Auto Poster state through a shared read-only adapter and renders the same contract for terminal and Telegram admin surfaces.
