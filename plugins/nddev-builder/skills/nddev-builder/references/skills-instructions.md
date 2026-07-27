# Skills, Rules, And Instructions

Use this reference when changing Cursor rules, Agent Skills, instructions, or
AGENTS.md guidance.

## Native paths

- Cursor project rules: `.cursor/rules/*.mdc`
- Cursor plugin rules: `<plugin>/rules/*.mdc`
- Cursor project skills: `.cursor/skills/<skill>/SKILL.md`
- Cursor user skills: `~/.cursor/skills/<skill>/SKILL.md`
- Cursor plugin skills: `<plugin>/skills/<skill>/SKILL.md`
- Workspace instructions: `AGENTS.md` in the project root or subdirectories.

Cursor may also load compatible skill roots, but this module should use Cursor
native plugin skills for its managed builder toolkit.

## AGENTS.md boundary

Repository `AGENTS.md` files are workspace instructions. They are not managed as
Cursor config-directory instructions by this module. Do not project or document
`CURSOR_CONFIG_DIR/AGENTS.md` as a runtime discovery path.

## Skill design checklist

- Keep `SKILL.md` lean and route to one-level `references/` files for detailed
  native surface guidance.
- Put deterministic repeated checks in `scripts/`.
- Keep facts that can change in code-owned files and refer to those files.
- Validate every routed reference path and script path.
- Do not add private QA, memory, evidence, waiver, or root harness material to a
  public plugin skill.

## Rule design checklist

- Use `.mdc` frontmatter for rule metadata.
- Make always-on rules short and policy-oriented.
- Put detailed workflows in skills or references instead of global rules.
