# VM Intelligence & Integrated Autonomous Brain v5.0.0

## Platform prerequisite recovery

v5.0.0 includes a fail-closed VM Core recovery stage because the live master project was
confirmed to have `shared/` present while `shared/vm_core` was physically absent.

Recovery uses only existing user-owned Git history, official release ZIPs, snapshots and
backups. No VM Core implementation is synthesized by VM Intelligence. A candidate must
pass module, source-safety, compile, isolated-import and current Admin/Search/Guard
regression gates before it is retained. Accepted recovery provenance and a deterministic
tree hash are recorded for auditability.

## Core operating loop

Observe -> Measure -> Detect -> Correlate -> Explain -> Prioritise -> Experiment ->
Learn -> Safely Act -> Verify -> Remember -> Report exceptions

The design deliberately separates intelligence from authority. A conclusion can be
high-confidence without automatically granting permission to perform a risky action.

## Live integrations

### Smart Auto Poster
Read-only operational adapter measures queue state, 24-hour delivery performance,
uncertain sends, account health/failure streaks, campaigns, destinations,
quarantines, warnings/errors, recommendations, heartbeat freshness and database size.

### VM Relationship Manager
Read-only operational adapter measures contact/follow-up workload, overdue work,
risk/attention queues, component health, forecasts, data quality, integration backlog,
repeated administrative patterns, backup status and database size.

### Universal Search
Uses VM Core SearchIndex statistics when available and read-only legacy index/search
audit counts where present.

### VM Guard and Admin Command Centre
Uses VM Core live runtime/component state. Self-healing is bounded by the existing
VM Core `auto_restart=true` policy; intentionally unmanaged services are not started.

## Intelligence engines implemented

- historical event and metric memory
- ecosystem scorecard and bot performance league
- native per-bot metrics
- anomaly detection
- persistent incident lifecycle and recurrence tracking
- evidence-based root-cause reports with confidence
- structured incident postmortems/autopsies
- recommendation engine
- automation-opportunity detector
- efficiency analysis
- experiment registry and outcome learning
- causal-evidence labeling: controlled experiments vs observational release effects
- improvement ledger
- operational goals and missed-goal escalation
- CTO-style engineering priority ranking
- P0-P4 Intelligence Inbox / manage-by-exception queue
- conservative predictive-maintenance trends
- capacity planning using measurements actually available
- configurable cost intelligence (never invents provider prices)
- technical-debt scanner
- AST code/dependency intelligence
- operational digital twin
- configuration drift monitoring using hashes only
- security exposure indicators without storing secret values
- release/source-change baselines and post-release learning
- impact-aware test planning
- automatic regression-test proposals from high-severity incidents
- meta-intelligence for Brain cycle reliability and explicit alert usefulness/noise
- data retention/knowledge ageing for raw operational events
- backup integrity verification
- daily executive brief and weekly engineering review
- Telegram exception notifications
- bounded self-healing using the existing VM Core supervisor
- safe what-if simulation that refuses unsupported guesses

## Telegram Intelligence cockpit

Admin Command Centre gains authenticated commands:

`/brain` `/inbox` `/insights` `/incidents` `/why [service]`
`/performance` `/league` `/predict` `/security` `/capacity`
`/recommendations` `/automation` `/efficiency` `/cto`
`/improvements` `/experiments` `/learning` `/causal`
`/goals` `/what_changed` `/testing` `/autopsy` `/meta`
`/twin` `/cost` `/simulate <action>` `/askvm <question>`
`/intelfeedback <incident_id> useful|noise` `/intelhelp`

Intelligence dispatch occurs only after the existing Admin authorization check.
The installer backs up Admin source, patches only a known compatible dispatch anchor,
syntax-checks it, runs Admin regression tests when available, restarts the service,
verifies it alive and automatically rolls back on a critical installation failure.

## Self-improvement model

VM earns autonomy through evidence.

- raw events age out automatically while lessons/experiments/incidents remain structured
- recurring incidents become automation candidates
- high-severity incidents generate regression-test proposals
- completed experiments become improvement-ledger evidence
- release changes are observed and later scored as improved/regressed/neutral
- alert feedback (`useful` / `noise`) is measured by meta-intelligence
- unsupported causal or simulation claims are explicitly refused
- no arbitrary self-rewriting is permitted

## Security/privacy boundaries

VM Intelligence does not autonomously delete master data, expose credentials, weaken
security, remove backups, change Telegram identity, perform irreversible migrations or
rewrite SAP/RM business logic.

`.env` drift is tracked using SHA-256 hashes only. Security scans report file paths and
counts, not secret values. Relationship and posting adapters read operational metadata,
not private message bodies.

## Passive outputs

The Windows Startup agent continuously maintains:

- `diagnostics/intelligence_report.json`
- `diagnostics/intelligence_report.txt`
- `diagnostics/intelligence_brief.txt`
- `diagnostics/intelligence_attention.json`
- `diagnostics/intelligence_weekly.txt`
- `diagnostics/intelligence_inbox.json`
- `diagnostics/intelligence_security.json`
- `diagnostics/intelligence_cto.json`
- `diagnostics/intelligence_postmortems.json`
- `diagnostics/intelligence_testing.json`
- `diagnostics/intelligence_predictive.json`
- `diagnostics/intelligence_scoreboard.json`
- `diagnostics/intelligence_digital_twin.json`
- `diagnostics/intelligence_meta.json`
- `logs/vm_intelligence_agent.log`
- `state/vm_intelligence.sqlite3`

## Honest measurement boundaries

The Brain does not invent CPU/memory capacity, paid-provider prices, causal conclusions
or statistical confidence that has not been measured. Those surfaces remain explicitly
"not measured", "not configured", or observational until real evidence exists.

## v4 objective-driven control plane

v4 adds a canonical runtime and governance layer above the existing v3 intelligence engines.

### Canonical Runtime Registry

Each discoverable bot receives a stable runtime ID plus canonical root, entrypoint,
manifest path, version, source hash, topology hash, management policy and optional
compatibility entrypoint. The registry is persisted in SQLite and
`state/runtime_registry.json`.

### Platform normalisation

The architecture scanner detects unresolved runtimes, multiple manifests/runnable
candidates, deep nesting and compatibility bridges. It creates a prioritised migration
plan, but source relocation/deletion is explicitly proposal-only in v5.0.0.

### Reliability / SLOs / error budgets

The Reliability Brain evaluates service-level objectives for platform score, posting
success, uncertain delivery, Admin/Guard availability, managed-service health and backup
integrity. Critical SLO conditions recommend reliability freeze and prevent automated
experiment/optimisation authority.

### Autonomy ladder and safe mode

- L0 Observe
- L1 Explain
- L2 Recommend
- L3 Prepare
- L4 Recover
- L5 Experiment
- L6 Optimize
- L7 Objective-driven

Default authority is L4 Recover, preserving the existing bounded recovery behavior.
Safe mode leaves observation/explanation/recovery available while capping effective
authority at L4.

### Objective engine

The initial objectives are:

1. Keep all VM services healthy.
2. Maximise useful automation safely.
3. Minimise unnecessary user attention.

Objectives produce measurable scores, guardrail violations and bounded next-action plans.
They do not grant permission to run arbitrary shell/code actions.

### Release and impact intelligence

AST-derived dependency edges map shared VM Core/Intelligence modules to dependent bots.
The release gate rejects candidates when critical incidents exist, SLOs are breached or
the candidate score regresses materially. Automatic release promotion remains disabled
in v5.0.0.

### Attention budget

Alert usefulness/noise feedback and automatic decisions are summarized around the north
star: **useful autonomous outcomes per unit user attention**.


## VM Intelligence v6.0.0

v6 adds an evidence-governed self-improvement layer above the v5 objective-driven
operating system. New autonomous paths pass one policy kernel. The platform measures
evidence quality, intervention durability, disaster-recovery readiness and attention cost;
it can propose runbook/architecture improvements in shadow or isolated workspaces, but
cannot directly rewrite certified production behaviour.

North star: useful autonomous outcomes per unit user attention.
