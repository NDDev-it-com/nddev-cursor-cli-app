# nddev-cursor-cli-app

Portable setup manager for Cursor CLI configuration. It manages one explicit
absolute Cursor config target, never the caller's live `~/.cursor` by default.

## Usage

```bash
python3 cli-tools/nddev_cursor_cli.py list
python3 cli-tools/nddev_cursor_cli.py plan --setup nddev-builder --profile full-auto --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py install --setup nddev-builder --profile full-auto --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py switch --setup nddev-builder --profile safe --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py migrate --setup nddev-builder --profile safe --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py restore --backup 0 --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py remove --target /absolute/cursor-config
```

The active public model is one content setup, `nddev-builder`, plus orthogonal
permission profiles. The default profile is `full-auto`; `safe` is available for
sandboxed allowlisted work. Legacy managed targets can be inspected, migrated,
restored, or removed, but they are not launchable.

New targets are created owner-private (`0700`) only under a real parent that is
current-user-owned and not writable by group/other, or a sticky directory.
Existing targets used for install, switch, migrate, restore, remove, software
install/update, or launch must already be owned by the current user and mode
`0700`; the manager reports `target:owner` or `target:mode` drift instead of
silently changing existing root permissions. Lifecycle lock and backup state
lives inside the target under `.nddev-cursor-cli/{lock,backups}`; sibling
`.nddev-*` lock or backup paths are ignored.
Existing target-local builder and runtime parent directories, including
`.nddev-cursor-home`, `bin`, and `.nddev-software`, must also be real
current-user-owned directories with mode `0700`; unsafe parents are reported as
drift and block launch before a child process starts.

## Software lifecycle

The Cursor setup lifecycle and Cursor Agent runtime lifecycle are separate.
`software-status`, `install-cli`, and `update-cli` manage a target-owned copy
of the current Cursor Agent runtime package from the official Cursor artifact
URL:

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

`launch` runs `agent` with `CURSOR_CONFIG_DIR` and an isolated `HOME` scoped
only to the child process:

```bash
python3 cli-tools/nddev_cursor_cli.py launch --target /absolute/cursor-config -- -p "summarize"
```

`launch` requires a clean managed setup plus current target-owned software,
executes only the absolute target `bin/agent`, never falls back to `PATH`, and
uses a fixed minimal child `PATH` of `/usr/bin:/bin`. The launcher uses
`/bin/bash`, rejects Cursor flags or subcommands that would override the managed
approval, sandbox, worktree, shell-integration, worker, or self-update
lifecycle, and uses only the pinned target-owned runtime tree, including its
bundled Node.js binary. The manager keeps the target lock through child
execution and managed-config restoration, then revalidates the `bin/agent`
inode and digest immediately before the subprocess handoff.

The setup/profile model also projects `nddev-builder` as a local native Cursor plugin
under `.nddev-cursor-home/.cursor/plugins/local/nddev-builder` inside the
selected target. The projection uses Cursor's plugin, rules, skills, custom
agents, and commands surfaces. It does not activate hooks or MCP servers and
does not provision Cursor team marketplaces.
