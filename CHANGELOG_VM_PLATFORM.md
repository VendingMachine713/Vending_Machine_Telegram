# VM Ecosystem Changelog

## 1.4.0 â€” Recovery + Reliability

### Validation and Windows reliability
- Run each bot test suite from its own bot directory with project-root `PYTHONPATH`.
- Capture test output via temporary files so descendant processes cannot keep validation pipes open.
- Add hard suite timeouts and process-tree termination on timeout.
- Fix deterministic SQLite connection closure in the VM Core Universal Search index.
- Harden managed PID tracking, duplicate-start protection, process settling and stop/restart cleanup.
- Exclude venv/cache noise from bot test inventories and routine database checks.

### Search / Guard compatibility recovery
- Recover eligible pre-v1.3 Search and Guard `main.py` entrypoints as `legacy_main.py` from the v1.3 safety snapshot.
- Preserve VM Core wrappers as the canonical `main.py`.
- Merge declared legacy dependencies into current requirements.
- Reject recovery when the entrypoint contains credential-value logging or likely hard-coded credentials.
- Supervise legacy Telegram children independently with backoff and component heartbeat reporting.
- Audit unknown legacy `core.py` compatibility without rewriting it.

### Runtime and diagnostics
- Add live runtime/component snapshots and `runtime-check`.
- Add autostart-state reporting.
- Add Git tracked-file security audit and storage audit.
- Add readable support TXT generation so diagnostics can be uploaded without ZIP extraction workarounds.
- Refresh support bundles from post-start live state rather than relying only on pre-start validation data.

### Relationship Manager safety
- Detect the newer outer v1.2 tree versus the older nested v1.0.2 copy.
- Ignore disposable nested `__pycache__` artifacts in the cleanup safety decision.
- Cleanup application archives the complete nested tree, verifies the archive, preserves newer outer README/launcher/version and merges missing historical changelog sections.
- Installer remains preview-only; no nested Relationship Manager deletion occurs automatically.

### Admin Command Centre v0.4.0
- Add `/runtime`, `/autostart`, `/recovery`, and read-only `/relationshipcleanup` visibility.

### Installer / rollback
- Pre-v1.4 safety snapshot.
- Critical-step automatic rollback.
- Full validation before managed service start.
- Post-start runtime verification with one recovery retry.
- Automatic final ZIP + readable TXT handoff to Downloads.

## 1.3.0 â€” Autonomous Operations Rollout
- Added managed Admin, Universal Search and VM Guard services, shared search/alerting and Windows logon startup.
