# Hooks

Use this reference when designing or reviewing Cursor hook artifacts.

## Native paths

- Project hooks: `.cursor/hooks.json`
- User hooks: `~/.cursor/hooks.json`
- Plugin hooks: `<plugin>/hooks/hooks.json`
- Hook scripts are commonly kept under `.cursor/hooks/`, `~/.cursor/hooks/`, or
  plugin `scripts/`.

## Native JSON shape

Cursor hook JSON uses a top-level `hooks` object where each event maps to an
array of hook entries. Command-based hook entries include a `command` string and
may include a `matcher` when the event supports filtering.

Common official events include session lifecycle, tool-use lifecycle, shell
execution, MCP execution, file read/edit, prompt submission, compaction,
subagent lifecycle, and stop events. Check official Cursor hook docs before
adding event-specific input or output handling.

## Public module boundary

The current managed builder projection does not install or activate hooks; the
machine-readable projection contract is owned by `config/nddev-contract.json`
and `build/manifest.json`. Hook work must remain a deterministic plan, checker,
or design artifact unless a later setup explicitly owns:

- the hook JSON path
- the handler script path
- timeout and failure behavior
- stdin/stdout JSON contract
- rollback and removal behavior
- non-live validation

## Review checklist

- Keep handlers target-owned, regular files, bounded, and executable only when
  intentionally installed.
- Prefer fail-closed behavior only when the handler and its validation are owned.
- Never write hooks into the caller's live home from this public manager.
