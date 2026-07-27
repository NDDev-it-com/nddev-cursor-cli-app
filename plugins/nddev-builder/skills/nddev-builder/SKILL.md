---
name: nddev-builder
description: Build, review, or validate NDDev Cursor CLI setup/profile, permissions, lifecycle, plugin, rules, skills, agents, commands, hooks, MCP, and release surfaces. Use when changing or checking nddev-cursor-cli-app public setup behavior or native Cursor builder artifacts.
---

# NDDev Builder

Use this skill as the entry point for public `nddev-cursor-cli-app` builder
work. Keep edits target-explicit, reversible, public-only, and backed by
module-local validation.

## Workflow

1. Identify the native surface being changed.
2. Read only the routed reference files below that match the work.
3. Prefer executable manager output and repository-owned facts over prose
   copies. In an installed projection, use `list --json`,
   `status --target <absolute-target> --json`, and
   `software-status --target <absolute-target> --json` from the public manager.
   In a repository checkout, use the manager source, public contracts, and
   public validator as code-owned facts.
4. Keep volatile versions, artifact pins, supported profile lists, and block
   lists machine-owned; route to the manager or validator rather than restating
   them in new docs.
5. Run the executable validation workflow from
   `references/validation-release.md` before handing off.

## Routing

- **Configuration and setup/profile model**: read
  `references/configuration-profiles.md`.
- **Permissions, approval, sandbox, and network policy**: read
  `references/permissions-sandbox.md`.
- **Agents and subagents**: read `references/agents-subagents.md`.
- **Skills, rules, instructions, and AGENTS.md behavior**: read
  `references/skills-instructions.md`.
- **Plugins, local installation, commands, and marketplace boundary**: read
  `references/plugins-marketplace.md`.
- **Hooks**: read `references/hooks.md`.
- **MCP**: read `references/mcp.md`.
- **Official install artifact, target-owned runtime, launch, migration, restore,
  and removal**: read `references/installation-lifecycle.md`.
- **Creator/checker/release validation workflow**: read
  `references/validation-release.md`.

## Boundaries

- Do not write private harness artifacts or live user configuration from this
  public toolkit.
- Do not install software, start MCP servers, activate hooks, approve MCPs, push,
  tag, or mutate team marketplace state.
- Treat legacy managed targets as inputs only for status, migrate, restore, and
  remove. Do not launch or switch them directly.
