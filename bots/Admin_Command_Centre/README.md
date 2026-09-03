# VM Admin Command Centre v0.3.0

The Admin Command Centre is the single Telegram administration surface for the Vending Machine Telegram ecosystem. Individual bots should not own duplicate admin Telegram bots.

## Setup

1. Copy `.env.example` to `.env`.
2. Add only `VM_ADMIN_BOT_TOKEN`.
3. Start the bot. If no admin is configured, the Windows console prints a one-time claim code.
4. Send `/claim <code>` to the bot in a private chat. Your numeric Telegram user ID is stored locally automatically.
5. Keep `VM_ADMIN_ALLOW_MUTATIONS=false` until read-only commands are verified.

## Universal Progress Engine

Read-only platform command:

- `/progress` - render every registered Universal Progress Engine surface in one operator view.

Registered surfaces now include Smart Auto Poster and VM Guard. The provider registry is intentionally extensible, so additional bots can be added without changing the progress rendering contract used by terminal and Telegram admin surfaces.

VM Guard is a continuous service rather than a finite campaign. Its progress bar therefore represents operational readiness, while metrics expose monitor-only versus active-moderation mode, risk threshold and recent Guard events.

## Smart Auto Poster controls

Read-only commands:

- `/poster` - show Smart Auto Poster controls.
- `/poster_status` - VM-managed runtime status and PID.
- `/poster_progress` - live Universal Progress Engine view using Smart Auto Poster's read-only queue, destination, event and heartbeat evidence.
- `/poster_health` - run Smart Auto Poster's existing `health` CLI through VM Core.
- `/poster_queue` - run Smart Auto Poster's existing `queue-capacity` CLI through VM Core.
- `/poster_campaigns` - run Smart Auto Poster's existing `campaigns` CLI through VM Core.

Mutating commands require `VM_ADMIN_ALLOW_MUTATIONS=true`:

- `/poster_start`
- `/poster_stop`
- `/poster_restart`

## Universal Progress Engine CLI

Render all registered progress surfaces:

```powershell
python -m shared.vm_core.progress_cli
python -m shared.vm_core.progress_cli all --json
```

Render one provider only:

```powershell
python -m shared.vm_core.progress_cli autoposter
python -m shared.vm_core.progress_cli guard
python -m shared.vm_core.progress_cli guard --json
```

The progress surfaces never send posts, change queue rows, retry uncertain deliveries, change Guard moderation mode, or modify campaign/schedule state.

## Architecture boundary

`Admin_Command_Centre` owns Telegram administration and authentication.

Each bot continues to own its operational behaviour and bot-specific data. Cross-bot operations use `shared/vm_core` interfaces. The Universal Progress Engine reads explicit bot/platform evidence through shared read-only providers and renders one stable contract for terminal and Telegram admin surfaces.
