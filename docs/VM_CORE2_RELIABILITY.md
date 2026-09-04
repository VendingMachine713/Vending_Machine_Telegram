# VM Core 3.0 — Core 2 Reliability Begins

Core 2 introduces one normalized health vocabulary across all permanent VM services.

## Health states

- `HEALTHY`
- `DEGRADED`
- `RECOVERING`
- `ATTENTION_REQUIRED`
- `OFFLINE`

## Universal health command

```powershell
python vm.py health-v2
```

The health engine currently evaluates:

- service classification
- required configuration readiness
- process/runtime state
- runnable entrypoint/launcher availability
- declared bot database integrity

A stopped but otherwise valid service is `DEGRADED`, not automatically treated as an emergency. Missing required configuration or database integrity failures escalate to `ATTENTION_REQUIRED`.

## Safety boundary

This stage is read-only apart from the existing platform service-state inspection. It does not restart services, modify Telegram sessions, mutate bot queues, retry deliveries, or resolve UNCERTAIN Smart Auto Poster work.

## Next Core 2 work

The next reliability layers will add heartbeat freshness, stale-runtime detection, recovery classification, watchdog policy, and safe self-healing with explicit approval boundaries.
