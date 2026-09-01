# VM Intelligence

VM Intelligence is the shared evidence and reasoning layer for the Vending Machine Telegram ecosystem.

## Goals

1. Every runnable bot publishes small structured operational events into VM Core.
2. Shared health, incidents, destination/account state, relationship/search signals and campaign evidence are queryable from one place.
3. Cross-bot reasoning is explainable: every signal points back to observed evidence.
4. Intelligence is read-only by default. Operational mutations remain governed by the existing service, queue and safety layers.
5. Telemetry failure must never take a production bot down.

## Event contract

Events are stored in `state/vm_platform.sqlite3` and use schema version 2 metadata:

- `event_type`: namespaced machine-readable type, for example `service.started` or `signal.guard_risk_elevated`
- `source`: canonical bot/service name
- `payload_json`: non-sensitive operational details
- `event_version`: event contract version
- `severity`: DEBUG / INFO / WARNING / ERROR / CRITICAL
- `subject_type`: service, destination, chat, contact, account, campaign, etc.
- `subject_id`: stable identifier for the subject
- `correlation_id`: run/process/case correlation identifier
- `evidence_json`: IDs, reason codes and other evidence needed to explain the event
- `created_at_utc`: UTC timestamp

Do not put bot tokens, API keys, passwords, raw session contents, message bodies or unrelated personal data into shared events.

## Publisher

Bots integrate using:

```python
from shared.vm_core.publisher import BotEventPublisher
publisher = BotEventPublisher("Example_Bot", ROOT)
publisher.started()
publisher.heartbeat(status="ok")
publisher.incident("network_error", "Telegram connection failed")
```

The publisher is failure-isolated: database/telemetry errors are recorded in `last_error` and are not raised into bot control flow.

## Current publishers

- Admin Command Centre: lifecycle + polling incidents
- Smart Auto Poster: process lifecycle + unhandled process incidents
- Universal Search: lifecycle + search activity signals
- VM Guard: lifecycle + elevated-risk signals
- VM Relationship Manager: lifecycle + component health/incidents

## Intelligence materialisation

`shared.vm_core.intelligence.materialize_intelligence()` reads shared evidence and creates two durable projections:

### Incidents

Operational conditions requiring attention. Incident keys are idempotent so repeated observations update an existing case instead of creating noise.

### Signals

Evidence-backed observations or opportunities with:

- score
- confidence
- rationale
- subject
- evidence references

Initial cross-bot reasoning includes:

- service-health incidents from shared health state
- error/critical event incident projection
- delivery-risk signals from posting uncertainty/failure events
- relationship dormancy + search/activity spike opportunity detection
- VM Guard risk suppression of relationship/activity opportunities

## Authority model

VM Intelligence does not automatically perform consequential actions in v1.3.0.

The intended progression is:

`Observe -> Correlate -> Recommend -> Governed Action -> Verify`

Future automatic actions must declare their evidence requirements, allowed authority, rollback behaviour and fail-closed conditions.

## Admin surface

The Admin Command Centre exposes:

- `/intelligence`
- `/brain`

Both refresh the materialised view and show service health, open incidents and active signals without changing bot state.

## Adding a new bot signal

1. Choose a stable namespaced event type.
2. Set a meaningful `subject_type` and stable `subject_id`.
3. Publish reason codes / IDs as evidence rather than raw sensitive content.
4. Use INFO for normal evidence and WARNING/ERROR/CRITICAL only for genuine operational severity.
5. Add an intelligence rule only when the inference can be explained from observed evidence.
6. Add tests for idempotency and failure isolation.
