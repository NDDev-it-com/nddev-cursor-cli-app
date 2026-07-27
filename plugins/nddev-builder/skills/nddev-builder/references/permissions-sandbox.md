# Permissions, Sandbox, And Network

Use this reference when changing approval, sandbox, network, or command
permission behavior.

## Native permission rules

Cursor CLI permission arrays contain strings such as:

- `Shell(commandBase)`
- `Read(pathOrGlob)`
- `Write(pathOrGlob)`
- `WebFetch(domainOrPattern)`
- `Mcp(server:tool)`

Deny rules take precedence over allow rules. Keep rule strings narrow and
deterministic. Do not add broad write, shell, network, or MCP permissions
without a setup/profile reason and a validator update.

## NDDev profile contract

The exact public mappings are code-owned by:

- `profiles/full-auto/profile.json`
- `profiles/full-auto/cli-config.json`
- `profiles/safe/profile.json`
- `profiles/safe/cli-config.json`
- `cli-tools/validate_public_contracts.py`

Do not add a review or balanced profile unless official Cursor semantics and the
NDDev contract both explicitly adopt it in code.

## Launch protections

`launch` must reject Cursor arguments or subcommands that override managed
approval, sandbox, worktree, network, MCP approval, shell integration, worker,
or self-update lifecycle. The exact block list is owned by
`cli-tools/nddev_cursor_cli.py` and checked by
`cli-tools/validate_public_contracts.py`.

## Review checklist

- Keep full-auto and safe as orthogonal profiles, not separate content setups.
- Keep provider secrets out of installer and launch environments.
- Preserve target-owned rollback and backup behavior when profile values change.
- Update tests or validators when a managed config key changes.
