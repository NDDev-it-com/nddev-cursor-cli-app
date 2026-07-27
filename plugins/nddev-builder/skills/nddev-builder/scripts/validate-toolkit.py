#!/usr/bin/env python3
"""Validate the public nddev-builder Cursor plugin toolkit."""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path

REQUIRED_REFERENCES = {
    "agents-subagents.md",
    "configuration-profiles.md",
    "hooks.md",
    "installation-lifecycle.md",
    "mcp.md",
    "permissions-sandbox.md",
    "plugins-marketplace.md",
    "skills-instructions.md",
    "validation-release.md",
}
REQUIRED_COMMANDS = {
    "nddev-agent.md",
    "nddev-hook-plan.md",
    "nddev-lifecycle.md",
    "nddev-mcp-plan.md",
    "nddev-permissions.md",
    "nddev-plugin-plan.md",
    "nddev-profile.md",
    "nddev-skill.md",
    "nddev-validate.md",
}
REQUIRED_COMPONENT_DIRS = {".cursor-plugin", "agents", "commands", "rules", "skills"}
DISALLOWED_PATH_PARTS = {"evidence", "memories", "private", "waiver", "waivers"}
PROJECTED_REFERENCE_PATTERN = re.compile(
    r"(?:^|[`\\s])((?:skills/nddev-builder/)?references/[A-Za-z0-9._/-]+)"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-root", default=".", help="nddev-cursor-cli-app root")
    return parser.parse_args(argv)


def read_text(path: Path, errors: list[str]) -> str:
    try:
        info = path.lstat()
    except FileNotFoundError:
        errors.append(f"missing file: {path}")
        return ""
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        errors.append(f"path must be a regular file: {path}")
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{path}: not UTF-8: {exc}")
        return ""


def validate_frontmatter(path: Path, text: str, errors: list[str]) -> None:
    if not text.startswith("---\n"):
        errors.append(f"{path}: missing YAML frontmatter")
        return
    end = text.find("\n---\n", 4)
    if end == -1:
        errors.append(f"{path}: unterminated YAML frontmatter")
        return
    frontmatter = text[4:end]
    if "name:" not in frontmatter or "description:" not in frontmatter:
        errors.append(f"{path}: frontmatter must include name and description")


def validate_rule_frontmatter(path: Path, text: str, errors: list[str]) -> None:
    if not text.startswith("---\n"):
        errors.append(f"{path}: missing YAML frontmatter")
        return
    end = text.find("\n---\n", 4)
    if end == -1:
        errors.append(f"{path}: unterminated YAML frontmatter")
        return
    frontmatter = text[4:end]
    if "description:" not in frontmatter:
        errors.append(f"{path}: rule frontmatter must include description")


def validate_json(path: Path, errors: list[str]) -> dict:
    text = read_text(path, errors)
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: invalid JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path}: top-level JSON value must be an object")
        return {}
    return value


def validate_projected_reference_paths(plugin_root: Path, errors: list[str]) -> None:
    skill_root = plugin_root / "skills" / "nddev-builder"
    for path in plugin_root.rglob("*.md"):
        text = read_text(path, errors)
        if "references/cursor-cli-baseline.json" in text:
            errors.append(f"{path}: must not route to non-projected baseline JSON")
        for match in PROJECTED_REFERENCE_PATTERN.finditer(text):
            reference = match.group(1).rstrip(".,);:")
            if reference == "references/":
                candidate = skill_root / "references"
            elif reference.startswith("references/"):
                candidate = skill_root / reference
            else:
                candidate = plugin_root / reference
            if not candidate.exists() or candidate.is_symlink():
                errors.append(f"{path}: unresolved projected reference path: {reference}")


def validate_tree(module_root: Path, errors: list[str]) -> None:
    plugin_root = module_root / "plugins" / "nddev-builder"
    skill_root = plugin_root / "skills" / "nddev-builder"
    manifest = validate_json(plugin_root / ".cursor-plugin" / "plugin.json", errors)
    if manifest.get("name") != "nddev-builder":
        errors.append("plugin manifest name must be nddev-builder")
    if "hooks" in manifest or "mcpServers" in manifest:
        errors.append("public builder manifest must not activate hooks or MCP servers")
    for key in ("rules", "skills", "agents", "commands"):
        if key not in manifest:
            errors.append(f"plugin manifest missing component key: {key}")
    for component in REQUIRED_COMPONENT_DIRS:
        path = plugin_root / component
        if not path.is_dir() or path.is_symlink():
            errors.append(f"plugin component must be a real directory: {component}")

    skill_text = read_text(skill_root / "SKILL.md", errors)
    validate_frontmatter(skill_root / "SKILL.md", skill_text, errors)
    references = {path.name for path in (skill_root / "references").glob("*.md")}
    commands = {path.name for path in (plugin_root / "commands").glob("*.md")}
    missing_refs = sorted(REQUIRED_REFERENCES - references)
    missing_commands = sorted(REQUIRED_COMMANDS - commands)
    if missing_refs:
        errors.append(f"missing required skill references: {missing_refs}")
    if missing_commands:
        errors.append(f"missing required command files: {missing_commands}")
    for name in REQUIRED_REFERENCES:
        marker = f"references/{name}"
        if marker not in skill_text:
            errors.append(f"entry SKILL.md does not route to {marker}")

    agent_text = read_text(plugin_root / "agents" / "nddev-builder.md", errors)
    validate_frontmatter(plugin_root / "agents" / "nddev-builder.md", agent_text, errors)
    rule_text = read_text(plugin_root / "rules" / "nddev-builder.mdc", errors)
    validate_rule_frontmatter(plugin_root / "rules" / "nddev-builder.mdc", rule_text, errors)

    for path in plugin_root.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            errors.append(f"plugin toolkit must not contain symlinks: {path}")
        lowered_parts = {part.lower() for part in path.relative_to(plugin_root).parts}
        if lowered_parts & DISALLOWED_PATH_PARTS:
            errors.append(f"plugin toolkit contains private-only path naming: {path}")

    for forbidden in (
        module_root / "setups" / "review",
        module_root / "profiles" / "review",
        module_root / "profiles" / "balanced",
    ):
        if forbidden.exists() or forbidden.is_symlink():
            errors.append(f"unsupported public profile/setup path exists: {forbidden}")
    validate_projected_reference_paths(plugin_root, errors)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    module_root = Path(args.module_root).resolve(strict=False)
    errors: list[str] = []
    validate_tree(module_root, errors)
    if errors:
        print(f"validate-toolkit.py: FAIL ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate-toolkit.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
