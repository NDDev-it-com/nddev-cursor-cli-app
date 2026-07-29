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

Targets are explicit, owner-bound directories. The manager reports unsafe
ownership, mode, symlink, hardlink, or parent drift instead of silently
normalizing an existing target. It keeps cooperative lifecycle locks across
mutating operations and launch cleanup, writes target-bound backups, and ignores
legacy sibling control state. Exact path names, modes, lock binding, backup
layout, and drift labels are code-owned by
`cli-tools/nddev_cursor_cli.py` and summarized by `config/nddev-contract.json`,
`build/manifest.json`, and `status --target <target> --json`.

The lock model is a cooperative same-UID boundary for manager operations and a
target-privacy boundary for other local users. It does not claim resistance to
deliberate same-UID tampering without a sandbox.

## Software lifecycle

The Cursor setup lifecycle and Cursor Agent runtime lifecycle are separate.
`software-status`, `install-cli`, and `update-cli` manage a target-owned copy
of the pinned official Cursor Agent runtime package:

```bash
python3 cli-tools/nddev_cursor_cli.py software-status --target /absolute/cursor-config --json
python3 cli-tools/nddev_cursor_cli.py install-cli --target /absolute/cursor-config --json
python3 cli-tools/nddev_cursor_cli.py update-cli --target /absolute/cursor-config --json
```

Production installs use only the official pinned artifact described by
`references/cursor-cli-baseline.json`, with release/runtime closure owned by
`build/manifest.json` and enforced by `cli-tools/nddev_cursor_cli.py`. npm and
pip install paths are not supported. Use `software-status --json` for the exact
local software state, drift, and current/repair/no-op outcomes.

`launch` runs Cursor Agent from the managed target with isolated runtime state
scoped only to the child process:

```bash
python3 cli-tools/nddev_cursor_cli.py launch --target /absolute/cursor-config -- -p "summarize"
```

By default, launch captures the manager caller's current working directory once
and passes that directory to Cursor as native `--workspace` while also using it
as the child process cwd. Use manager-owned `--workspace /path/to/project`
before the separator to select a different existing project directory.

The first `--` after manager options is the manager/Cursor separator and is not
forwarded. A second or later `--` is preserved as an intentional Cursor
argument.

`launch` requires a clean managed setup plus current target-owned software,
blocks Cursor arguments that would override managed lifecycle boundaries, and
restores managed config after the child exits or raises. Exact child
environment, blocked arguments, executable verification, runtime write surface,
and handoff mechanics are owned by `cli-tools/nddev_cursor_cli.py`; the public
contract is summarized in `config/nddev-contract.json` and
`build/manifest.json`.

The setup/profile model also projects `nddev-builder` as a local native Cursor plugin
inside the selected target's isolated home. The projection uses Cursor's
plugin, rules, skills, custom agents, and commands surfaces. It does not
activate hooks or MCP servers and does not provision Cursor team marketplaces.
Exact projection paths and installed surfaces are owned by
`config/nddev-contract.json`, `build/manifest.json`, and `status --json`.
