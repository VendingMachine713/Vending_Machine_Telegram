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

`shared.vm_core.intelligence.materialize_intelligence()` reads shared evidence and creates durable incidents and signals.

Initial cross-bot reasoning includes:

- service-health incidents from shared health state
- error/critical event incident projection
- delivery-risk signals from posting uncertainty/failure events
- relationship dormancy + search/activity spike opportunity detection
- VM Guard risk suppression of relationship/activity opportunities

## Evidence-governed recommendations

VM Core schema version 3 turns active cross-bot signals into durable recommendations. Each recommendation records a stable key, type, subject, priority, confidence, action, rationale, producing rule and supporting evidence.

Current rules recommend safe delivery reconciliation, relationship review and guard-risk review. Recommendations never execute Telegram actions, and uncertain Smart Auto Poster jobs remain protected from automatic retry.

## Recommendation governance

VM Brain includes explicit operator governance in `shared.vm_core.governance`.

Allowed transitions are deliberately conservative:

- `PROPOSED -> ACCEPTED` or `DISMISSED`
- `BLOCKED -> DISMISSED`
- `ACCEPTED -> COMPLETED` or `DISMISSED`
- terminal states cannot be silently reopened

Every decision writes an auditable correlated event. Governance changes metadata only and does not execute Telegram actions.

## Verification and learning

Completed recommendations may receive one verified outcome through `shared.vm_core.learning`.

Outcome types:

- `POSITIVE`
- `NEUTRAL`
- `NEGATIVE`
- `UNKNOWN`

Outcome data includes bounded value score, confidence, actor, note and evidence. Rule performance is descriptive and grouped by rule ID/version. VM Brain does not self-modify rules from these outcomes.

## Controlled calibration

VM Core v1.6.0 adds advisory calibration in `shared.vm_core.calibration`.

The calibration engine:

- requires at least 8 known outcomes before proposing a scoring adjustment
- evaluates positive-rate evidence and confidence-weighted value
- uses a conservative Wilson lower-bound test before marking a rule `STRONG`
- identifies persistently weak rules as `WEAK`
- identifies material confidence underperformance as `OVERCONFIDENT`
- marks evidence-consistent rules `STABLE`
- caps any proposed score delta to +/-10 points
- never applies a proposal automatically

Calibration proposals are recommendations about the intelligence rules themselves, not active configuration changes.

## Governed rule registry

VM Core v1.7.0 adds `shared.vm_core.rule_registry` as the controlled boundary between calibration advice and future scoring changes.

The registry provides:

- durable calibration change proposals
- explicit `APPROVED` / `REJECTED` governance before activation
- immutable per-rule registry versions
- parent-version lineage
- bounded score deltas capped at +/-10 points
- deterministic staged rollout percentages
- activation audit events
- rollback to the prior active registry version
- passive registry summaries

Proposal lifecycle:

`PROPOSED -> APPROVED -> ACTIVATED -> ROLLED_BACK`

or:

`PROPOSED -> REJECTED`

Approval and activation are deliberately separate operations. An approved proposal does nothing until an operator explicitly activates it. Registry activation records a governed calibration version and rollout policy; it does not send Telegram messages, alter Smart Auto Poster queues, or grant external-action authority.

`effective_score_delta()` exposes the staged, governed adjustment for recommendation-scoring integration. The rule registry itself does not bypass the existing recommendation, governance or safety layers.

Operator tool:

```powershell
python tools/vm_brain_rules.py summary
python tools/vm_brain_rules.py sync
python tools/vm_brain_rules.py list
python tools/vm_brain_rules.py approve 1 --actor admin
python tools/vm_brain_rules.py activate 1 --actor admin --rollout 10
python tools/vm_brain_rules.py rollback 1 --actor admin
```

Automatic approval, automatic activation and automatic external execution remain disabled.

## Authority model

VM Intelligence does not automatically perform consequential external actions in v1.7.0.

The progression is now:

`Observe -> Correlate -> Recommend -> Govern -> Verify -> Learn -> Calibrate -> Governed Change -> Stage -> Verify -> Roll Back if needed`

A calibration proposal is not authority to alter a rule. Approval is not activation. Registry activation is versioned, bounded and reversible, and it still does not authorize Telegram execution.

## Admin surface

The Admin Command Centre exposes read-only `/intelligence` and `/brain` views. Rule-registry administration remains available through the operator tool at this stage.

## Adding a new bot signal

1. Choose a stable namespaced event type.
2. Set a meaningful `subject_type` and stable `subject_id`.
3. Publish reason codes / IDs as evidence rather than raw sensitive content.
4. Use INFO for normal evidence and WARNING/ERROR/CRITICAL only for genuine operational severity.
5. Add an intelligence rule only when the inference can be explained from observed evidence.
6. Add tests for idempotency and failure isolation.
