# VM Intelligence

Current production release: **v5.0.0 â€” Integrated Autonomous Brain**

VM Intelligence is the shared analysis, learning, decision and bounded-automation layer
for the Vending_Machine_Telegram ecosystem. It is not a separate duplicate bot.

## Core loop

Observe â†’ Measure â†’ Detect â†’ Correlate â†’ Explain â†’ Prioritise â†’ Experiment â†’
Learn â†’ Safely Act â†’ Verify â†’ Report by exception.

## Main operator surfaces

Telegram through Admin Command Centre:

`/brain`, `/inbox`, `/insights`, `/incidents`, `/why`, `/performance`, `/league`,
`/predict`, `/security`, `/capacity`, `/cto`, `/efficiency`, `/recommendations`,
`/automation`, `/goals`, `/goalset`, `/goalon`, `/goaloff`, `/improvements`,
`/experiments`, `/experimentstart`, `/experimentfinish`, `/learning`, `/causal`,
`/what_changed`, `/testing`, `/autopsy`, `/meta`, `/twin`, `/cost`, `/simulate`,
`/askvm`, `/intelfeedback`, `/intelhelp`.

Windows operations:

- `tools\Intelligence\INTELLIGENCE_STATUS.ps1`
- `tools\Intelligence\DOCTOR_INTELLIGENCE.ps1`
- `tools\Intelligence\BACKUP_INTELLIGENCE.ps1`
- `tools\Intelligence\RESTART_INTELLIGENCE.ps1`
- `tools\Intelligence\TEST_INTELLIGENCE.ps1`
- `tools\Intelligence\ROLLBACK_INTELLIGENCE_V4.ps1`

## Safety

Automatic recovery is restricted to services whose effective VM lifecycle policy has
`auto_restart=true`. Smart Auto Poster and Relationship Manager are not restarted merely
because their processes are intentionally stopped.

The Brain does not automatically rewrite production bot business logic, expose credentials,
delete master data, weaken security, remove backups or perform irreversible migrations.

See `VM_INTELLIGENCE_PRODUCTION.md` for architecture and `VM_INTELLIGENCE_v3_RELEASE_NOTES.md`
for the release summary.


## VM Intelligence v6.0.0

v6 adds an evidence-governed self-improvement layer above the v5 objective-driven
operating system. New autonomous paths pass one policy kernel. The platform measures
evidence quality, intervention durability, disaster-recovery readiness and attention cost;
it can propose runbook/architecture improvements in shadow or isolated workspaces, but
cannot directly rewrite certified production behaviour.

North star: useful autonomous outcomes per unit user attention.
