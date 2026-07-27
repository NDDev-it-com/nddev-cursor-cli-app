# Plugins, Commands, And Marketplace Boundary

Use this reference when changing the local builder plugin, commands, or
marketplace-facing documentation.

## Native plugin layout

Cursor plugins use a required manifest at `.cursor-plugin/plugin.json` and may
include component directories:

- `rules/`
- `skills/`
- `agents/`
- `commands/`
- `hooks/hooks.json`
- `mcp.json`
- `assets/`
- `scripts/`

The public manager installs only the local plugin projection under the
launch-isolated home:

`.nddev-cursor-home/.cursor/plugins/local/nddev-builder`

It does not install into the caller's live `~/.cursor`.

## Managed components

This setup intentionally projects rules, skills, agents, and commands. It does
not declare hook or MCP components in the plugin manifest.

## Commands

Command files in `commands/*.md` should route to the same references as
`skills/nddev-builder/SKILL.md`. Keep commands actionable and surface-specific.

## Marketplace boundary

Cursor has native plugin marketplace surfaces, but this public module does not
create, emulate, publish, or mutate marketplace state. Treat marketplace work as
documentation or design until a separate owner explicitly adds a publish
lifecycle.

## Review checklist

- Keep `.cursor-plugin/plugin.json` valid JSON with local component paths.
- Keep local plugin paths deterministic and target-owned.
- Do not add variables requiring secrets unless a later setup owns secret
  injection and validation.
- Run the toolkit validator after adding any plugin file.
