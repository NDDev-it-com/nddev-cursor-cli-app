# Security Policy

## Supported surface

Security reporting covers the setup catalog, lifecycle CLI, public contracts,
documentation, native Cursor builder projection, and GitHub workflows in this
repository. Only the latest numeric release is supported.

## Reporting a vulnerability

Report vulnerabilities privately through GitHub Security Advisories for
`NDDev-it-com/nddev-cursor-cli-app`. Do not publish credentials, tokens,
private configuration, or backup contents in an issue or pull request.

## Baseline controls

- The CLI never defaults to `~/.cursor`; target operations require an explicit
  absolute `--target`.
- Managed files reject symlinks, special files, and hard-link aliases.
- Setup switching preserves unmanaged target files and co-owned Cursor CLI
  configuration keys.
- Backup envelopes and installed stamps are bound to the canonical target.
- Mutations use a target-internal lock, bounded target-internal backup
  rotation, postcondition checks, and rollback on failure.
- Existing target roots used for mutation, restore, migrate, remove, software
  install/update, or launch must be current-user-owned and mode `0700`.
- Existing target-local builder and runtime parent directories, including
  `.nddev-cursor-home`, `bin`, and `.nddev-software`, must be real
  current-user-owned `0700` directories; unsafe parents are drift and block
  launch before subprocess handoff.
- Launch keeps a persistent `.nddev-cursor-cli/lock` file locked with
  nonblocking `fcntl.flock` through child execution and managed-config
  restoration. The lock parent plus ephemeral launch image are `0500` during
  launch for ordinary same-UID unlink/replace denial; the target root, isolated
  HOME, target-local TMPDIR, config/session paths, and installed runtime tree
  remain writable.
- The executable handoff is a write-protected verified-path handoff with
  immediate launch-image inode and digest revalidation before subprocess start.
  It does not claim portable fd execution or deliberate same-UID chmod
  resistance without a sandbox.
- The builder capability is projected as a local native Cursor plugin with
  rules, skills, and agents. This manager does not provision Cursor team
  marketplace state.
