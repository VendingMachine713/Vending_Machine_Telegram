# VM Intelligence

VM Intelligence is the shared evidence and reasoning layer for the Vending Machine Telegram ecosystem.

## Goals

1. Every runnable bot publishes small structured operational events into VM Core.
2. Shared health, incidents, destination/account state, relationship/search signals and campaign evidence are queryable from one place.
3. Cross-bot reasoning is explainable: every signal points back to observed evidence.
4. Intelligence is read-only by default. Operational mutations remain governed by the existing service, queue and safety layers.
5. Telemetry failure must never take a production bot down.

## Event contract

Events are stored in `state/vm_platform.sqlite3` and use structured metadata:

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

## Evidence-governed recommendations

VM Core schema version 3 turns active cross-bot signals into durable recommendations. Each recommendation records:

- a stable idempotency key, type, subject, priority and confidence
- the proposed action and human-readable rationale
- the rule ID and rule version that produced it
- the supporting signal IDs and safety controls
- a lifecycle state: `PROPOSED`, `BLOCKED`, `ACCEPTED`, `DISMISSED`, `COMPLETED` or `EXPIRED`

Current rules recommend safe delivery reconciliation, relationship review and guard-risk review. A guard signal on the same chat blocks relationship outreach. Recommendations never execute Telegram actions, and uncertain Smart Auto Poster jobs remain protected from automatic retry.

Run `python -m shared.vm_core.cli intelligence` to refresh and display the shared view.

## Recommendation governance

VM Brain now includes an explicit operator-governance layer in `shared.vm_core.governance`.

Allowed state transitions are deliberately conservative:

- `PROPOSED -> ACCEPTED` or `DISMISSED`
- `BLOCKED -> DISMISSED`
- `ACCEPTED -> COMPLETED` or `DISMISSED`
- `DISMISSED`, `COMPLETED` and `EXPIRED` are terminal

A blocked recommendation cannot be accepted. Every valid decision writes an auditable `recommendation.*` event correlated to the recommendation record. Governance transitions change VM Intelligence metadata only; they do not send Telegram messages, retry posting jobs, modify bot-owned databases or execute the recommended action.

Operator tool:

```powershell
python tools/vm_brain_governance.py summary
python tools/vm_brain_governance.py list
python tools/vm_brain_governance.py accept "recommendation:relationship_activity:123" --actor admin
python tools/vm_brain_governance.py complete "recommendation:relationship_activity:123" --actor admin
python tools/vm_brain_governance.py history "recommendation:relationship_activity:123"
```

The tool is intentionally separate from Telegram action execution. `automatic_execution` remains `False` throughout this stage.

## Authority model

VM Intelligence does not automatically perform consequential actions in v1.4.0.

The intended progression is:

`Observe -> Correlate -> Recommend -> Govern -> Governed Action -> Verify -> Learn`

Future automatic actions must declare their evidence requirements, allowed authority, rollback behaviour and fail-closed conditions. No recommendation status change is itself permission to perform an external action.

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
