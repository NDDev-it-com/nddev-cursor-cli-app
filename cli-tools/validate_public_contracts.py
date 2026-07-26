#!/usr/bin/env python3
"""Validate public nddev-cursor-cli-app contracts without private inputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_VERSION_KEYS = {
    "build_version",
    "cursor_cli_identity",
    "cursor_config_schema",
    "nddev_builder_plugin_version",
    "python_requires",
    "runtime_baseline_ref",
    "schema_version",
}


def load_json(relative: str, errors: list[str]) -> dict | None:
    path = ROOT / relative
    if not path.is_file():
        errors.append(f"missing required contract file: {relative}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{relative}: unreadable or invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{relative}: top-level value must be an object")
        return None
    return value


def main() -> int:
    errors: list[str] = []
    version = load_json("build/version.json", errors)
    manifest = load_json("build/manifest.json", errors)
    contract = load_json("config/nddev-contract.json", errors)
    baseline = load_json("references/cursor-cli-baseline.json", errors)
    plugin = load_json("plugins/nddev-builder/.cursor-plugin/plugin.json", errors)

    version_text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version is not None:
        missing = REQUIRED_VERSION_KEYS - set(version)
        if missing:
            errors.append(f"build/version.json: missing required keys {sorted(missing)}")
        if version.get("build_version") != version_text:
            errors.append("VERSION and build/version.json:build_version disagree")
        if version.get("cursor_cli_identity") != "agent":
            errors.append("build/version.json: cursor_cli_identity must be agent")
        if version.get("cursor_config_schema") != 1:
            errors.append("build/version.json: cursor_config_schema must be 1")

    if manifest is not None and version is not None:
        if manifest.get("build_version") != version.get("build_version"):
            errors.append("build/manifest.json:build_version disagrees with build/version.json")
        if manifest.get("setup_ids") != ["full-auto", "review", "safe"]:
            errors.append("build/manifest.json: unexpected setup_ids")
        projection = manifest.get("builder_projection")
        if not isinstance(projection, dict) or projection.get("default_on") is not True:
            errors.append("build/manifest.json: builder_projection.default_on must be true")

    if contract is not None:
        if contract.get("contract_version") != 2:
            errors.append("config/nddev-contract.json: contract_version must be 2")
        if contract.get("github_repository") != "NDDev-it-com/nddev-cursor-cli-app":
            errors.append("config/nddev-contract.json: unexpected github_repository")
        if "skeleton" in contract:
            errors.append("config/nddev-contract.json: skeleton must be removed")
        managed = contract.get("managed_state", {}).get("managed_files")
        if managed != ["cli-config.json"]:
            errors.append("config/nddev-contract.json: managed_state.managed_files mismatch")

    if baseline is not None:
        if baseline.get("cli_identity", {}).get("command") != "agent":
            errors.append("references/cursor-cli-baseline.json: CLI command must be agent")
        if baseline.get("configuration", {}).get("environment_override") != "CURSOR_CONFIG_DIR":
            errors.append("references/cursor-cli-baseline.json: missing CURSOR_CONFIG_DIR")

    setup_ids: list[str] = []
    for setup_dir in sorted((ROOT / "setups").iterdir()):
        if not setup_dir.is_dir():
            continue
        setup = load_json(f"setups/{setup_dir.name}/setup.json", errors)
        config = load_json(f"setups/{setup_dir.name}/cli-config.json", errors)
        if setup is not None:
            if setup.get("id") != setup_dir.name:
                errors.append(f"setups/{setup_dir.name}/setup.json: id mismatch")
            if setup.get("managed_files") != ["cli-config.json"]:
                errors.append(f"setups/{setup_dir.name}/setup.json: managed_files mismatch")
            if setup.get("builder_projection") != "default-on":
                errors.append(f"setups/{setup_dir.name}/setup.json: builder must be default-on")
            setup_ids.append(setup_dir.name)
        if config is not None:
            if config.get("version") != 1:
                errors.append(f"setups/{setup_dir.name}/cli-config.json: version must be 1")
            if "permissions" not in config:
                errors.append(f"setups/{setup_dir.name}/cli-config.json: missing permissions")

    if setup_ids != ["full-auto", "review", "safe"]:
        errors.append(f"setups/: unexpected setup directories {setup_ids}")

    if plugin is not None and version is not None:
        if plugin.get("name") != "nddev-builder":
            errors.append("plugins/nddev-builder: plugin name must be nddev-builder")
        if plugin.get("version") != version.get("nddev_builder_plugin_version"):
            errors.append("plugins/nddev-builder: version disagrees with build/version.json")
    for relative in (
        "plugins/nddev-builder/rules/nddev-builder.mdc",
        "plugins/nddev-builder/skills/nddev-builder/SKILL.md",
        "plugins/nddev-builder/agents/nddev-builder.md",
    ):
        if not (ROOT / relative).is_file():
            errors.append(f"missing builder projection source: {relative}")

    if errors:
        print(f"validate_public_contracts.py: FAIL ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
