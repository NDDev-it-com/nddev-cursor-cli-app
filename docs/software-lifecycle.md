# Cursor Agent software lifecycle

`nddev-cursor-cli-app` can manage the Cursor Agent runtime inside the same
explicit target used for Cursor CLI configuration. It does not install into the
caller home, system prefix, npm global prefix, or pip environment.

## Commands

- `software-status --target <absolute-target>` is read-only and reports
  `present`/`presence` for target-owned software paths.
- `install-cli --target <absolute-target>` installs only when managed software
  presence is absent.
- `update-cli --target <absolute-target>` requires existing target-owned
  software presence. It can repair safe partial state such as a missing,
  malformed, or mode-drifted identity stamp; symlink, hardlink, and wrong-type
  paths fail closed before artifact reads.
  If the target is already current, it returns an idempotent no-op without downloading.
- `launch --target <absolute-target> -- ...` requires both a clean setup stamp
  and current target-owned software, then executes only `<target>/bin/agent`.
  It rejects Cursor flags or subcommands that would override the managed
  approval, sandbox, worktree, shell-integration, worker, or self-update
  lifecycle.

## Source and integrity

The current official release id is `2026.07.23-e383d2b`, as used by
`https://cursor.com/install`. Production installs use only the corresponding
`https://downloads.cursor.com/lab/2026.07.23-e383d2b/{os}/{arch}/agent-cli-package.tar.gz`
artifacts. The exact SHA-256 and size for each supported macOS/Linux artifact
are pinned in `references/cursor-cli-baseline.json`.

## Archive safety and rollback

The archive reader never extracts an artifact wholesale. It streams only the
official `dist-package/` runtime tree, requires `cursor-agent`, `node`, and
`index.js`, normalizes target-owned file modes, and rejects absolute paths,
parent traversal, Windows-drive paths, NUL paths, symlink, hardlink, device,
duplicate, group/world-writable, special-mode, and oversize members.

Updates stage a complete version tree under
`.nddev-software/cursor-cli/versions/2026.07.23-e383d2b/` and then atomically
rename it into place. On failure, the manager restores the previous version
tree, `bin/agent`, and `NDDEV-CURSOR-CLI-SOFTWARE.json`. The installed
`bin/agent` is a target-owned launcher that executes the pinned target-owned
runtime tree, including its bundled `node`; launch never falls back to a live or
system Node.js binary.
