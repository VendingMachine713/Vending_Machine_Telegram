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

All five primary bot folders now have a progress provider:

- Admin Command Centre: operator/control-surface runtime readiness and recent admin events.
- Smart Auto Poster: queue progress, current destination/task, ETA, events, runtime heartbeats and recovery guidance.
- VM Guard: operational readiness, monitor-only/active mode, risk threshold, runtime freshness and recent Guard events.
- Universal Search: index size, saved-watch state and passive alert-delivery progress. Terminal alert failures switch the surface to ATTENTION.
- VM Relationship Manager: intelligence coverage, overdue/dormant/low-health counts and the highest-priority suggested action for manual review.

The provider registry remains extensible, so future bots/services can join without changing the terminal or Telegram rendering contract.

## Smart Auto Poster controls

Read-only commands:

- `/poster` - show Smart Auto Poster controls.
- `/poster_status` - VM-managed runtime status and PID.
- `/poster_progress` - focused Smart Auto Poster Universal Progress view.
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
python -m shared.vm_core.progress_cli admin
python -m shared.vm_core.progress_cli autoposter
python -m shared.vm_core.progress_cli guard
python -m shared.vm_core.progress_cli search
python -m shared.vm_core.progress_cli relationships
python -m shared.vm_core.progress_cli admin --json
```

The progress surfaces are visibility-only: they never send posts/messages, mutate bot queues, trigger retries, change Guard moderation mode, contact people, or modify campaign/schedule/service state.

## Architecture boundary

`Admin_Command_Centre` owns Telegram administration and authentication.

Each bot continues to own its operational behaviour and bot-specific data. Cross-bot operations use `shared/vm_core` interfaces. The Universal Progress Engine reads explicit bot/platform evidence through shared read-only providers and renders one stable contract for terminal and Telegram admin surfaces.
