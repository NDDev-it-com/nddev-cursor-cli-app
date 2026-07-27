# Configuration And Profiles

Use this reference when creating, changing, or reviewing the public setup and
profile model.

## Native Cursor locations

- Global CLI config: `~/.cursor/cli-config.json`.
- Project CLI config: `<project>/.cursor/cli.json`.
- Manager launch override: `CURSOR_CONFIG_DIR=<absolute-target>` points Cursor
  Agent at the target-local `cli-config.json` for the child process only.

Do not claim that Cursor discovers `AGENTS.md` through `CURSOR_CONFIG_DIR`.
Workspace instructions are covered in `skills-instructions.md`.

## Public module model

- Content setup metadata lives at `setups/nddev-builder/setup.json`.
- Permission profiles live at `profiles/<profile>/profile.json`.
- Profile-owned Cursor config lives at `profiles/<profile>/cli-config.json`.
- The manager writes target-local `cli-config.json` plus
  `NDDEV-CURSOR-CLI-SETUP.json`.

Use `cli-tools/nddev_cursor_cli.py` as the source of truth for supported setup
and profile ids. Do not duplicate that list in generated docs.

## Config shape

Profile `cli-config.json` must be JSON object with the native Cursor CLI fields
that the manager owns:

- `version`
- `editor.vimMode`
- `permissions.allow`
- `permissions.deny`
- `approvalMode`
- `sandbox.mode`
- `sandbox.networkAccess`
- `network.useHttp1ForAgent`
- `hints`
- `notifications`

The exact active profile mappings are owned by the `profiles/` JSON files and
validated by `cli-tools/validate_public_contracts.py`.

## Review checklist

- Keep setup selection orthogonal to permission profile selection.
- Preserve unmanaged config keys during install, switch, migrate, launch repair,
  and remove.
- Reject unmanaged targets with existing Cursor state rather than overwriting.
- Keep legacy setup ids readable only for status, migrate, restore, and remove.
