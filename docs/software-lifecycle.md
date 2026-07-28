# Cursor Agent software lifecycle

`nddev-cursor-cli-app` can manage the Cursor Agent runtime inside the same
explicit target used for Cursor CLI configuration. It does not install into the
caller home, system prefix, npm global prefix, or pip environment.

## Commands

- `software-status --target <absolute-target>` is read-only and reports
  target-owned software state without executing Cursor.
- `install-cli --target <absolute-target>` installs only when managed software
  presence is absent.
- `update-cli --target <absolute-target>` requires existing target-owned
  software presence. It can repair safe partial state and is an idempotent
  no-op when the target is already current.
- `remove-cli --target <absolute-target>` removes only manager-owned Cursor
  Agent software state while preserving setup, auth, and unrelated target state.
- `launch --target <absolute-target> -- ...` requires both a clean setup stamp
  and current target-owned software, then executes the managed runtime with
  isolated child state.
  It rejects Cursor arguments that would override managed lifecycle boundaries.
  Legacy setup stamps must be migrated or removed before launch.

Exact status fields, drift labels, target path requirements, backup/control
layout, lock binding, child environment, blocked argument set, and launch
handoff are intentionally not duplicated here. The executable owner is
`cli-tools/nddev_cursor_cli.py`; machine-readable public contract summaries
live in `config/nddev-contract.json` and `build/manifest.json`. For a concrete
target, use `status --target <absolute-target> --json` and
`software-status --target <absolute-target> --json`.

The lifecycle guarantee is cooperative: manager operations use target-bound
state and lifecycle locks to avoid racing other well-behaved manager processes,
including launch cleanup and managed-config restoration. Target privacy protects
against other local users according to the current contract, but this is a
no-sandbox same-UID boundary. It does not claim resistance to deliberate
same-user tampering outside the manager.

## Source and integrity

Production installs use only the pinned official Cursor artifact described by
`references/cursor-cli-baseline.json`. That baseline owns the current official
release id, artifact URLs, supported platform artifact map, sizes, and SHA-256
digests. `build/manifest.json` owns the runtime closure published with this
module version.

The supported NDDev host IDs are `macos-arm64`, `macos-x64`,
`ubuntu-glibc-arm64`, and `ubuntu-glibc-x64`. Ubuntu desktop and server hosts
share the same `ID=ubuntu` plus glibc preflight, and Cursor publishes no
official Ubuntu/glibc version floor for this agent release. Upstream artifact
paths remain Cursor's own vendor names, including `darwin/*` and `linux/*`;
`windows`, `non-ubuntu-linux`, `linux-musl`, and `unsupported-architecture`
hosts fail closed before locks, target creation, download, staging, or launch.

## Archive safety and rollback

The archive reader is bounded and fail-closed, and updates stage a complete
target-owned runtime before an atomic swap. On failure, the manager restores the
previous target-owned software state. Exact member allowlists, runtime
inventory, file modes, launcher implementation, path policy, rollback state, and
handoff verification are owned by `cli-tools/nddev_cursor_cli.py` and summarized
by `config/nddev-contract.json`, `build/manifest.json`, and
`software-status --json`.

Cursor commands can write target-local runtime/process state and can rewrite
managed config defaults even when no login is attempted. Manager `launch`
therefore keeps lifecycle protection through child execution and restores the
selected setup's managed config keys while preserving unowned config keys. Use
the manager's JSON status commands for the exact status-neutral runtime state
rules.

## Builder plugin projection

The setup manager projects the public `nddev-builder` toolkit as a native local
Cursor plugin under the launch-isolated home. The toolkit includes rules, Agent
Skills with routed references and validation scripts, custom agents, and
commands. It does not install hook definitions, MCP server definitions, live
credentials, or marketplace state. Exact projection paths and installed surface
lists are owned by `config/nddev-contract.json`, `build/manifest.json`, and
`status --json`.
