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
- Mutations use a sibling lock, bounded backup rotation, postcondition checks,
  and rollback on failure.
- Existing target roots used for mutation, restore, migrate, remove, software
  install/update, or launch must be current-user-owned and mode `0700`.
- Launch keeps the target lock through child execution and managed-config
  restoration; the lock is the cooperative same-user boundary and target-root
  `0700` is the cross-user boundary.
- The builder capability is projected as a local native Cursor plugin with
  rules, skills, and agents. This manager does not provision Cursor team
  marketplace state.
