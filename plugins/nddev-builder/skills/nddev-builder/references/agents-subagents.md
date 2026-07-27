# Agents And Subagents

Use this reference when changing Cursor custom agent artifacts.

## Native paths

- Project subagents: `.cursor/agents/*.md`
- User subagents: `~/.cursor/agents/*.md`
- Plugin subagents: `<plugin>/agents/*.md`

The managed public builder plugin projects its agent files under the isolated
launch home at `.nddev-cursor-home/.cursor/plugins/local/nddev-builder/agents/`.

## Native file shape

A subagent file is Markdown with YAML frontmatter followed by the prompt body.
Use `name` and `description` in frontmatter. Use optional Cursor fields only
when the behavior is intentionally owned, such as model/tool/read-only/background
settings.

## Authoring checklist

- Keep each agent narrow enough that automatic routing is predictable.
- State whether the agent is reviewing, creating, checking, or releasing.
- Do not include live credentials, private repository paths, or generated
  evidence.
- Point to code-owned contract files for versions, pins, setup ids, profiles,
  and launch block lists.
- Validate frontmatter and projection through the public validator before handoff.
