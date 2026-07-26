# nddev-cursor-cli-app

Portable setup manager for Cursor CLI configuration. It manages one explicit
absolute Cursor config target, never the caller's live `~/.cursor` by default.

## Usage

```bash
python3 cli-tools/nddev_cursor_cli.py list
python3 cli-tools/nddev_cursor_cli.py plan --setup safe --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py install --setup safe --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py switch --setup review --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py restore --backup 0 --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py remove --target /absolute/cursor-config
```

## Software lifecycle

The Cursor setup lifecycle and Cursor Agent binary lifecycle are separate.
`software-status`, `install-cli`, and `update-cli` manage a target-owned copy
of the current Cursor Agent binary from the official Cursor artifact URL:

```bash
python3 cli-tools/nddev_cursor_cli.py software-status --target /absolute/cursor-config --json
python3 cli-tools/nddev_cursor_cli.py install-cli --target /absolute/cursor-config --json
python3 cli-tools/nddev_cursor_cli.py update-cli --target /absolute/cursor-config --json
```

Production installs use the pinned `https://cursor.com/install` release id
`2026.07.23-e383d2b` and pinned SHA-256 digests for the official
`downloads.cursor.com` artifacts. npm and pip install paths are not supported.
`software-status` reports `present` and `presence` for target-owned software
paths. `install-cli` requires absent software presence. `update-cli` requires
existing software presence, can repair safe partial state such as a missing or
mode-drifted identity stamp, and is an idempotent no-op when `software-status`
reports `current=true`.

`launch` runs `agent` with `CURSOR_CONFIG_DIR` scoped only to the child process:

```bash
python3 cli-tools/nddev_cursor_cli.py launch --target /absolute/cursor-config -- -p "summarize"
```

`launch` requires a clean managed setup plus current target-owned software,
executes only the absolute target `bin/agent`, never falls back to `PATH`, and
rejects Cursor flags or subcommands that would override the managed approval,
sandbox, worktree, shell-integration, worker, or self-update lifecycle.

The setup variants also project `nddev-builder` as a local native Cursor plugin
under the selected target. The projection uses Cursor's plugin, rules, skills,
and custom agents surfaces. This module does not provision Cursor team
marketplaces.
