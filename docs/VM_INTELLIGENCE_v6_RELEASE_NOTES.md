# VM Intelligence v6.0.0 Release Notes

## Self-Improving Evidence-Governed Platform

v6.0.0 is the accumulated production candidate from the v5.0.1 calibrated baseline through the v6 roadmap.
It changes the platform from an L7 planner with separate Intelligence features into one evidence-governed
closed loop. Planning may operate at L7; every production action still receives independent capability,
policy, evidence, reliability, security, rollback and backup checks.

### Evidence & truth
- freshness classes: LIVE, FRESH, AGING, STALE, INVALID
- direct/verified/derived/predicted/inferred evidence quality
- evidence-quality score is separate from platform health
- poor or stale evidence can reduce/defer authority and never raises it

### Central policy kernel
Policy outcomes are:
- ALLOW
- ALLOW_SHADOW
- ALLOW_EXPERIMENT
- REQUIRE_APPROVAL
- DEFER
- DENY

The kernel now gates both the real managed-service recovery path and the L5 experiment-start path.
Permanent denials include blind uncertain resend, direct autonomous production source rewriting,
credential or permission change, irreversible migration, and bypass of security/regression gates.
There is no global L7 execution grant.

### Reliability & intervention learning
v6 explicitly separates:
- immediate recovery success
- 24-hour recurrence
- seven-day recurrence
- root-cause success

A restart can therefore be a successful recovery while still being a poor permanent fix.

### Runbook evolution
Repeated workflows can become DRAFT revisions with a bounded runbook definition. The lifecycle is:
DRAFT -> SIMULATED -> SHADOW -> PROVISIONAL -> CERTIFIED_L4/L5 or REVOKED.
The platform never automatically replaces a certified runbook.

### Prediction calibration
Due predictions can be labelled TRUE_POSITIVE, FALSE_POSITIVE, TRUE_NEGATIVE or FALSE_NEGATIVE when
actual outcome evidence exists. Brier score and observed accuracy are retained for calibration.

### Disaster recovery
The Brain reports latest backup age, last verified restore, RPO, RTO and restore confidence. If no
verified restore drill exists, restore confidence remains zero rather than being inferred from backup existence.
Automatic destructive restore remains disabled.

### Architecture modernisation
Known compatibility/deep-topology debt can become isolated modernisation candidates. Candidate plans require
an isolated worktree, exact impacted tests, bridge-disabled simulation, full regression and a reversible migration.
production_mutation remains false at proposal stage.

### Strategic operator
The planner now maintains NOW, 24H, 7D, 30D and QUARTER horizons and an objective portfolio weighted toward
reliability, user attention and security. Execution authority remains policy-kernel + capability-specific.

### Attention governor
User attention remains a first-class resource. The north star remains:
**useful autonomous outcomes per unit user attention**.

### Exact release regression surface
Canonical bot release validation captures exact discovered test IDs before installation and fails closed if the
post-install test surface unexpectedly adds or removes tests, even if all remaining tests pass.
