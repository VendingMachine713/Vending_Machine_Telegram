# VM Core 3.1 — Heartbeats and Universal Watchdog

VM Core 3.1 implements Core 2 Reliability stages 3.1 and 3.2.

## Heartbeat contract

Every VM service can publish the same operational heartbeat fields:

- service
- instance ID
- status
- active task
- counters
- last successful action time
- last error
- recovery state
- observed timestamp

Heartbeats are stored in the shared platform database and classified by freshness:

- FRESH: <= 60 seconds
- STALE: > 60 and <= 180 seconds
- EXPIRED: > 180 seconds

The thresholds are conservative defaults and can be made service-specific later.

Use:

```powershell
python vm.py heartbeats
```

Existing `BotEventPublisher.heartbeat()` calls now write both the durable heartbeat registry and the existing telemetry event. Failure remains isolated so observability cannot crash a bot.

## Universal watchdog

```powershell
python vm.py watchdog
```

The first watchdog slice is read-only. It compares:

- tracked process state
- heartbeat freshness
- universal health state

It detects:

- live process with no heartbeat
- stale heartbeat
- expired heartbeat
- fresh heartbeat with no tracked live process
- universal-health attention state

No restart, retry, queue mutation or Telegram action is performed.

## Next stages

3.3 Failure Classification and 3.4 Recovery Policy will consume watchdog findings. Automatic recovery remains disabled until classification and policy boundaries are explicitly validated.
