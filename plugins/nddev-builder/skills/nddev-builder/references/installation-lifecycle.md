# Installation And Lifecycle

Use this reference when changing target-owned software install, status, launch,
migration, restore, or removal.

## Public lifecycle commands

- `list [--json]`: list active content setups and profiles.
- `plan --target <absolute-target> [--setup <id>] [--profile <id>] [--json]`:
  read-only change plan.
- `install --target <absolute-target> [--setup <id>] [--profile <id>] [--json]`:
  write current setup/profile into an empty or missing target.
- `update --target <absolute-target> [--json]`: refresh an existing target using
  its installed setup/profile identity.
- `switch --target <absolute-target> [--setup <id>] [--profile <id>] [--json]`:
  switch an existing current managed target.
- `migrate --target <absolute-target> [--setup <id>] [--profile <id>] [--json]`:
  convert a legacy managed target.
- `status --target <absolute-target> [--json]`: read managed state.
- `restore --backup <0..9> --target <absolute-target> [--json]`: restore a
  target-bound backup.
- `remove --target <absolute-target> [--json]`: remove managed setup files and
  preserve unmanaged config keys.
- `software-status`, `install-cli`, `update-cli`, `remove-cli`: manage
  target-owned Cursor Agent software.
- `launch --target <absolute-target> -- ...`: run only target-owned `bin/agent`.

Use `cli-tools/nddev_cursor_cli.py` as the source of truth for exact arguments,
blocked launch overrides, artifact pins, platform handling, and stamp schema.

## Lifecycle invariants

- Require absolute non-symlink targets with existing real parents.
- Preserve unmanaged state and unmanaged config keys.
- Use target-bound backups and rollback on failure.
- Keep software install separate from setup/profile install.
- Keep launch environment child-process-only.
- Strip provider secrets from installer and launch environments.
- Refuse legacy managed launch and switch until migration.

## Install provenance

Official runtime version, artifact URL template, sizes, and digests are
machine-owned by the public manager and checked by public validators. Installed
toolkit users should use `software-status --target <absolute-target> --json`
for target-owned runtime state instead of copying volatile ledger values into
prose surfaces.
