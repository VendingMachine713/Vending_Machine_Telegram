# v1.4 Migration Strategy

## Search and Guard

v1.3 introduced VM Core wrappers into the permanent Search and Guard folders. The live support bundle
showed older `core.py` implementations and tests still present, which means replacing the entrypoint alone
did not preserve the complete prior runtime.

v1.4 uses the safety snapshot created immediately before v1.3:
`backups/pre_v1_3_ecosystem_*`

If the legacy entrypoint passes the credential-safety scan it is copied to:
`legacy_main.py`

The VM Core wrapper remains `main.py` and supervises `legacy_main.py`.

This provides:
- shared VM Core health/index/alerts
- preserved existing Telegram functionality
- independent restart/backoff for the legacy Telegram component
- a reversible migration path

## Relationship Manager

No automatic deletion occurs in v1.4.

The live diff establishes the outer copy as newer. The cleanup command only becomes eligible when:
- the outer version is newer than nested
- all differing source files are in the known safe comparison set
- there are no nested-only source/config/session/database files
- any skipped files are disposable cache bytecode only

Applied cleanup always archives the nested folder before removal.
