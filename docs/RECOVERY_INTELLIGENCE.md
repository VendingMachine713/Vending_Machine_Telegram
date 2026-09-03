# VM Recovery Intelligence

Recovery Intelligence is the policy layer between passive visibility and autonomous self-healing.

## Goals

- classify failures before acting;
- distinguish safe service recovery from operator-required conditions;
- preserve Smart Auto Poster delivery safety, especially `UNCERTAIN` items;
- avoid broad restart cascades;
- make the default operator experience read-only and low maintenance.

## Classification model

- `HEALTHY` — process evidence is alive; no action.
- `SAFE_RECOVERY` — process is unhealthy and the bot manifest explicitly authorizes auto-start or auto-restart.
- `REVIEW` — unhealthy, but no manifest permission exists for automatic recovery.
- `BLOCKED` — evidence suggests authentication/credentials, Telegram limits, session problems or delivery ambiguity; automatic recovery is intentionally prohibited.
- `UNKNOWN` — evidence is insufficient; observe rather than guess.

## Safety boundaries

Recovery planning never retries Telegram deliveries, changes queue rows, modifies campaigns or schedules, edits credentials, or resolves `UNCERTAIN` deliveries automatically.

The guarded executor is dry-run by default and only accepts `SAFE_RECOVERY` decisions that were explicitly marked automatic. It is capped to one action per pass by default to prevent restart cascades.

## Operator commands

Admin Command Centre:

```text
/recovery
```

Local terminal:

```powershell
python -m shared.vm_core.recovery_cli
python -m shared.vm_core.recovery_cli --json
```

One-command PowerShell wrapper:

```powershell
.\tools\vm_core\RECOVERY_STATUS.ps1
```

No per-bot PowerShell configuration is required for this read-only status path.

## Next stage

After validation, the next layer should add durable restart-attempt history, cooldown/backoff, recovery verification and escalation so safe self-healing can run continuously without restart loops.
