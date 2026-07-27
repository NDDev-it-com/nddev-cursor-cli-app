# nddev-cursor-cli-app Agent Instructions

This public repository owns the independently usable Cursor CLI setup manager.
Keep implementation, contracts, docs, and public validators inside this module.
Private harness tests, evidence, memories, and operational skills are owned by
the parent control plane and must not be added here.

## Scope

- Public manager: `cli-tools/nddev_cursor_cli.py`
- Public validator: `cli-tools/validate_public_contracts.py`
- Public contracts: `config/nddev-contract.json`, `build/manifest.json`,
  `build/version.json`, `references/cursor-cli-baseline.json`
- Public setup/profile catalogs: `setups/`, `profiles/`
- Public builder plugin: `plugins/nddev-builder/`

## Rules

- Keep setup selection orthogonal to permission profiles.
- Preserve unmanaged target files and unmanaged Cursor config keys.
- Keep target-owned backups, locks, rollback, bounded I/O, and secret isolation.
- Do not write live user Cursor state or private harness artifacts.
- Do not claim Cursor runtime discovery paths that are not owned by official
  Cursor behavior and this module's code.
- Use Conventional Commits without co-author trailers.

## Validation

Run public, module-local checks from this repository root:

```bash
python3 plugins/nddev-builder/skills/nddev-builder/scripts/validate-toolkit.py --module-root .
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_cursor_cli.py list --json
git diff --check
```
