# VM Platform Foundation v0.2.0

This is an additive upgrade for the existing `Vending_Machine_Telegram` platform.

## v0.2 additions

- Smarter entrypoint discovery:
  - standard root entrypoints
  - Windows launcher parsing
  - common nested source folders
  - confidence level for discovered entrypoints
- New `py vm.py inspect` command.
- Safe project-structure reports:
  - `diagnostics/project_structure.txt`
  - `diagnostics/project_structure.json`
- `.env` and known credential filenames are never read by the structure reporter.
- Large runtime/cache directories are skipped.
- Inventory schema upgraded to v2.
- Manifest previews now include detected entrypoint confidence.

## Commands

```powershell
py vm.py status
py vm.py doctor
py vm.py inspect
py vm.py inventory
py vm.py manifests
py vm.py manifests --write
py vm.py test
```

Existing bot files, databases, configs, sessions and existing manifests are preserved.
